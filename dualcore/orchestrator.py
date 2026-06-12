"""The grounded dual-agent loop.

Coder writes code → Test Designer writes an executable suite → the sandbox runs
it → real failures are fed back to the Coder → repeat until the suite is green or
we run out of rounds → Reviewer gives a final verdict.

``run()`` is a generator of plain-dict events so it stays decoupled from Flask/SSE
and is easy to unit-test with a fake LLM and sandbox.
"""

from __future__ import annotations

from collections.abc import Iterator

from .agents import Agents, extract_code
from .config import Settings
from .llm import LLM
from .sandbox import ExecutionResult, Sandbox

Event = dict[str, object]

PYTEST_CMD = [
    "python", "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider",
    "--json-report", "--json-report-file=report.json", "test_solution.py",
]

_MAX_TRACEBACK = 1500
_MAX_FAILURES_TEXT = 6000
_MAX_OUTPUT_TAIL = 1500


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated {len(text) - limit} chars]"


def _result_payload(result: ExecutionResult, round_num: int) -> Event:
    report = result.report
    return {
        "type": "execution",
        "round": round_num,
        "result": {
            "all_passed": result.all_passed,
            "timed_out": result.timed_out,
            "setup_error": result.setup_error,
            "duration_s": round(result.duration_s, 2),
            "summary": report.summary_line() if report else "no structured report",
            "counts": {
                "total": report.total if report else 0,
                "passed": report.passed if report else 0,
                "failed": report.failed if report else 0,
                "errors": report.errors if report else 0,
                "skipped": report.skipped if report else 0,
            },
            "failures": [
                {
                    "name": c.name,
                    "outcome": c.outcome,
                    "message": _truncate(c.message, 400),
                    "traceback": _truncate(c.traceback, _MAX_TRACEBACK),
                }
                for c in (report.failures if report else [])
            ],
            "stdout_tail": _truncate(result.stdout, _MAX_OUTPUT_TAIL),
            "stderr_tail": _truncate(result.stderr, _MAX_OUTPUT_TAIL),
        },
    }


def _failures_text(result: ExecutionResult) -> str:
    """Compact, model-friendly description of a failing run (for the fixer)."""
    if result.timed_out:
        return (
            "Execution TIMED OUT — likely an infinite loop or code that is far too "
            "slow. Find and fix the cause."
        )
    parts: list[str] = []
    report = result.report
    if report:
        parts.append(f"Result: {report.summary_line()}.")
        for i, case in enumerate(report.failures, 1):
            block = f"\n{i}. {case.name} [{case.outcome}]"
            if case.message:
                block += f"\n   message: {case.message}"
            if case.traceback:
                block += f"\n   traceback:\n{_truncate(case.traceback, _MAX_TRACEBACK)}"
            parts.append(block)
    if not report or not report.parsed:
        parts.append("No structured report was produced. Raw output:")
        parts.append(_truncate(result.stdout, _MAX_OUTPUT_TAIL))
        parts.append(_truncate(result.stderr, _MAX_OUTPUT_TAIL))
    return _truncate("\n".join(parts), _MAX_FAILURES_TEXT)


def _exec_summary(result: ExecutionResult) -> str:
    """One-liner for the reviewer."""
    if result.setup_error:
        return f"Could not run tests: {result.setup_error}"
    if result.timed_out:
        return "Tests timed out (possible infinite loop)."
    if result.report:
        verdict = "ALL TESTS PASSED" if result.all_passed else "SOME TESTS FAILED"
        return f"{verdict} — {result.report.summary_line()}."
    return "Process exited " + str(result.exit_code)


class Orchestrator:
    """Drives the Coder ↔ Test Designer ↔ Sandbox loop."""

    def __init__(
        self, llm: LLM, sandbox: Sandbox, settings: Settings, model: str | None = None
    ) -> None:
        self._agents = Agents(llm, settings, model)
        self._sandbox = sandbox
        self._settings = settings

    def _stream_lane(
        self, lane: str, token_iter: Iterator[str]
    ) -> Iterator[tuple[Event | None, str]]:
        """Yield (token_event, accumulated) pairs, ending with (None, full_text)."""
        acc = ""
        for tok in token_iter:
            acc += tok
            yield {"type": "token", "lane": lane, "text": tok}, acc
        yield None, acc

    def run(
        self, requirement: str, instructions: str, profile: str, rounds: int
    ) -> Iterator[Event]:
        rounds = max(1, min(rounds, self._settings.max_rounds))
        timeout = self._settings.exec_timeout
        try:
            # ── Round 1: write initial code ──────────────────────────────
            yield {"type": "phase", "phase": "coding", "round": 1, "lane": "coder",
                   "message": "Agent A is writing the initial implementation…"}
            code_raw = ""
            for ev, acc in self._stream_lane(
                "coder", self._agents.stream_code(requirement, instructions, profile)
            ):
                if ev:
                    yield ev
                code_raw = acc
            code = extract_code(code_raw)
            yield {"type": "message", "lane": "coder", "round": 1,
                   "label": "Round 1 · Initial Draft", "content": code_raw}

            # ── Design the test suite (once, against the initial code) ────
            yield {"type": "phase", "phase": "testing", "round": 1, "lane": "tester",
                   "message": "Agent B is designing an executable test suite…"}
            tests_raw = ""
            for ev, acc in self._stream_lane(
                "tester",
                self._agents.stream_tests(requirement, instructions, profile, code),
            ):
                if ev:
                    yield ev
                tests_raw = acc
            tests = extract_code(tests_raw)
            yield {"type": "message", "lane": "tester", "round": 1,
                   "label": "Test Suite", "content": tests_raw}

            # ── Execute / refine loop ────────────────────────────────────
            result: ExecutionResult | None = None
            for round_num in range(1, rounds + 1):
                yield {"type": "phase", "phase": "executing", "round": round_num,
                       "lane": "runtime",
                       "message": f"Round {round_num}: running the suite in the sandbox…"}
                result = self._sandbox.execute(
                    {"solution.py": code, "test_solution.py": tests},
                    PYTEST_CMD, timeout=timeout, profile=profile,
                )
                yield _result_payload(result, round_num)

                if result.setup_error:
                    yield {"type": "error",
                           "message": f"Sandbox unavailable: {result.setup_error}"}
                    yield {"type": "done", "passed": False, "rounds": round_num}
                    return

                if result.all_passed:
                    break
                if round_num == rounds:
                    break

                # Refine
                yield {"type": "phase", "phase": "fixing", "round": round_num + 1,
                       "lane": "coder",
                       "message": f"Round {round_num + 1}: Agent A is fixing the failures…"}
                fix_raw = ""
                for ev, acc in self._stream_lane(
                    "coder",
                    self._agents.stream_fix(
                        requirement, instructions, profile, code, tests,
                        _failures_text(result),
                    ),
                ):
                    if ev:
                        yield ev
                    fix_raw = acc
                code = extract_code(fix_raw)
                yield {"type": "message", "lane": "coder", "round": round_num + 1,
                       "label": f"Round {round_num + 1} · Refined Code", "content": fix_raw}

            # ── Final review ─────────────────────────────────────────────
            yield {"type": "phase", "phase": "reviewing", "round": 0, "lane": "reviewer",
                   "message": "Agent B is writing the final review…"}
            review_raw = ""
            for ev, acc in self._stream_lane(
                "reviewer",
                self._agents.stream_review(
                    requirement, code, tests, _exec_summary(result) if result else ""
                ),
            ):
                if ev:
                    yield ev
                review_raw = acc
            yield {"type": "message", "lane": "reviewer", "round": 0,
                   "label": "Final Review", "content": review_raw}

            yield {"type": "done",
                   "passed": bool(result and result.all_passed),
                   "rounds": rounds}

        except Exception as exc:  # surface any LLM/runtime error to the client
            yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
