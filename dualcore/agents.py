"""The three agent roles and their prompts.

- **Coder** (Agent A): writes and later fixes ``solution.py``.
- **Test Designer** (Agent B): writes an executable ``test_solution.py``.
- **Reviewer** (Agent B in review mode): gives a final quality verdict.

Every method streams tokens (for live UI) and the caller extracts the code block
from the accumulated text with :func:`extract_code`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

from .config import Settings
from .llm import LLM, Message

# ── Code extraction ─────────────────────────────────────────────────────────

_FENCE = re.compile(r"```([\w+.-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)
_PY_LANGS = {"python", "py", "python3"}


def extract_code(text: str) -> str:
    """Pull the solution/test source out of a markdown response.

    Prefers the longest python-tagged fenced block; falls back to the longest
    fenced block of any language; finally to the whole text.
    """
    blocks = [(lang.lower(), body) for lang, body in _FENCE.findall(text)]
    if not blocks:
        return text.strip()
    python_blocks = [body for lang, body in blocks if lang in _PY_LANGS]
    candidates = python_blocks or [body for _, body in blocks]
    return max(candidates, key=len).strip("\n")


# ── Profile-specific guidance ───────────────────────────────────────────────

_CODER_PROFILE_HINT = {
    "basic": "This is a general task. Use only the Python standard library.",
    "ml": (
        "This is a machine-learning task. numpy and torch are available — write "
        "clean, idiomatic PyTorch (e.g. subclass torch.nn.Module) where appropriate."
    ),
}

_TESTER_PROFILE_HINT = {
    "basic": "- Use only pytest and the Python standard library.",
    "ml": (
        "- This is a PyTorch task. In addition to functional correctness, verify "
        "TENSOR behaviour: output shape for given input shapes, dtype, that the "
        "forward pass runs, that `loss.backward()` populates gradients (no None "
        "grads) on trainable parameters, parameter counts if specified, "
        "batch-dimension handling, and determinism under a fixed `torch.manual_seed`. "
        "Use small tensors for speed."
    ),
}


def _profile_hint(table: dict[str, str], profile: str) -> str:
    return table.get(profile, table["basic"])


# ── System prompts ──────────────────────────────────────────────────────────

def _coder_system(profile: str) -> str:
    return f"""You are Agent A, the Coder — an expert Python engineer.
Write COMPLETE, correct, runnable code for the user's requirement.

Hard requirements:
- The code is saved as `solution.py` and imported by a separate test file as
  `import solution` / `from solution import ...`. Expose the solution as
  module-level functions/classes — do NOT bury logic inside `if __name__ == "__main__"`.
- No `input()`, no network calls, and no blocking or long-running code at import time.
  Guard any demo with `if __name__ == "__main__":`.
- Use type hints and concise docstrings. Handle edge cases and raise meaningful exceptions.
- Assume tests run offline; keep external I/O behind functions tests can monkeypatch.
{_profile_hint(_CODER_PROFILE_HINT, profile)}

Respond in EXACTLY this format:
## Analysis
One short paragraph on your approach.

## Implementation
```python
# complete contents of solution.py
```

## Assumptions
Bullet list of assumptions (or "None")."""


def _fixer_system(profile: str) -> str:
    return f"""You are Agent A, the Coder, fixing your own code.
Your code was run against a pytest suite and some tests failed. You are given the
real failures (tracebacks). Produce a corrected, COMPLETE `solution.py` that passes.

Rules:
- The TEST SUITE IS THE SPECIFICATION. Read each failing test and match its EXACT
  expected behaviour — the asserted return value, OR the specific exception type
  (e.g. a test using `pytest.raises(ValueError)` means raise ValueError, not
  TypeError; a test asserting `f(None) is False` means return False, do not raise).
- Keep the public API stable (same names/signatures) — the tests import them.
- Fix the root cause. Do NOT special-case the test inputs or delete functionality.
- If a test is genuinely wrong (contradicts the requirement), note it briefly in
  "Changes Made", but still fix everything you legitimately can.
- Same constraints as before: importable module, no blocking code at import, type hints.
{_profile_hint(_CODER_PROFILE_HINT, profile)}

Respond in EXACTLY this format:
## Changes Made
Numbered list mapping each fix to the failure it addresses.

## Implementation
```python
# complete corrected contents of solution.py
```"""


def _tester_system(profile: str) -> str:
    return f"""You are Agent B, the Test Designer — a meticulous test engineer.
Given a requirement and Agent A's implementation, write a COMPLETE pytest file that
rigorously verifies the code. It runs in an isolated sandbox with NO network access.

The file is saved as `test_solution.py` beside `solution.py`. Import the code under
test (e.g. `import solution` or `from solution import name`).

Design tests that actually catch bugs:
- Derive expected behaviour from the REQUIREMENT, not from the implementation. Use the
  implementation only to learn the public API (names and signatures).
- Cover: normal cases; boundary/edge cases (empty, zero, negative, large, None,
  duplicates); error handling (assert exceptions with `pytest.raises`); and a few
  adversarial inputs.
- Be deterministic: seed randomness; never use real network/time/files (use
  `tmp_path`, `monkeypatch`, or `unittest.mock` to isolate I/O).
- Keep each test small, independent, and clearly named. Write at least 6 tests.
{_profile_hint(_TESTER_PROFILE_HINT, profile)}

Respond in EXACTLY this format:
## Test Plan
2-4 bullets describing the scenarios you cover.

## Test Suite
```python
# complete contents of test_solution.py
```"""


_REVIEWER_SYSTEM = """You are Agent B in review mode — a senior code reviewer.
The code has ALREADY been executed against the test suite; you are given the result.
Trust that result for correctness. Give a concise FINAL assessment focused on code
quality, security, and gaps the tests might miss.

Respond in EXACTLY this format:
## Final Verdict
[PASS ✓ | NEEDS WORK ⚠] — one confident sentence (PASS only if tests passed and you
see no serious issues).

## Quality Summary
2-4 sentences on strengths, readability, security, and performance.

## Suggestions
Up to 3 concrete, optional improvements (or "None")."""


# ── User-message builders ───────────────────────────────────────────────────

def _with_instructions(body: str, instructions: str) -> str:
    instructions = (instructions or "").strip()
    if instructions:
        return f"{body}\n\nAdditional user instructions (follow these):\n{instructions}"
    return body


# ── Agents ──────────────────────────────────────────────────────────────────

class Agents:
    """Streaming wrappers around the LLM for each agent role."""

    def __init__(self, llm: LLM, settings: Settings, model: str | None = None) -> None:
        self._llm = llm
        self._settings = settings
        self._model = model or settings.model

    def _stream(
        self, system: str, user: str, *, temperature: float, max_tokens: int | None = None
    ) -> Iterator[str]:
        messages: Sequence[Message] = [{"role": "user", "content": user}]
        yield from self._llm.stream(
            system, messages, temperature=temperature, max_tokens=max_tokens, model=self._model
        )

    def stream_code(
        self, requirement: str, instructions: str, profile: str
    ) -> Iterator[str]:
        user = _with_instructions(
            f"Write Python code for this requirement:\n\n{requirement}", instructions
        )
        return self._stream(_coder_system(profile), user, temperature=0.2)

    def stream_fix(
        self,
        requirement: str,
        instructions: str,
        profile: str,
        code: str,
        tests: str,
        failures: str,
    ) -> Iterator[str]:
        user = _with_instructions(
            f"Requirement:\n{requirement}\n\n"
            f"Your current solution.py:\n```python\n{code}\n```\n\n"
            f"The test suite (test_solution.py):\n```python\n{tests}\n```\n\n"
            f"Test run results:\n{failures}\n\n"
            "Fix solution.py so the suite passes.",
            instructions,
        )
        return self._stream(_fixer_system(profile), user, temperature=0.2)

    def stream_tests(
        self, requirement: str, instructions: str, profile: str, code: str
    ) -> Iterator[str]:
        user = _with_instructions(
            f"Requirement:\n{requirement}\n\n"
            f"Agent A's implementation (solution.py):\n```python\n{code}\n```\n\n"
            "Write the pytest suite.",
            instructions,
        )
        return self._stream(_tester_system(profile), user, temperature=0.4)

    def stream_review(
        self, requirement: str, code: str, tests: str, execution_summary: str
    ) -> Iterator[str]:
        user = (
            f"Requirement:\n{requirement}\n\n"
            f"Final solution.py:\n```python\n{code}\n```\n\n"
            f"Test suite:\n```python\n{tests}\n```\n\n"
            f"Execution result:\n{execution_summary}\n\n"
            "Give your final review."
        )
        return self._stream(
            _REVIEWER_SYSTEM, user, temperature=0.2, max_tokens=1024
        )
