"""
DualCore — Dual Agentic AI Coding Assistant
Agents: Agent A (Coder) <-> Agent B (Debugger) with streaming SSE
Backend: Flask + Groq API (free, no credit card required)
"""

import os
import json
from flask import Flask, render_template, request, Response, stream_with_context
from groq import Groq                   
from dotenv import load_dotenv


load_dotenv()

app = Flask(__name__)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ── Model config ──────────────────────────────────────────────────────────────
# MODEL = "llama-3.3-70b-versatile"   # best free model on Groq for coding
MODEL = "openai/gpt-oss-120b" # faster, cheaper, still very capable for many coding tasks
MAX_TOKENS = 2048

# ── System prompts ────────────────────────────────────────────────────────────
SYSTEM_A_INITIAL = """You are Agent A — an expert Python software engineer.
Your job is to write clean, complete, well-documented Python code for the user's requirement.\
The indentation should be correct, and the code should be runnable as-is. If the requirement is ambiguous, make reasonable assumptions but note them in comments.

Guidelines:
- Always write COMPLETE, runnable Python code (no placeholders like "# TODO")
- Use type hints on all functions
- Add Google-style docstrings
- Handle edge cases and raise meaningful exceptions
- Prefer standard library; use third-party only when clearly better
- Include a brief `if __name__ == "__main__":` demo when useful

Response format (strictly follow this):
## Analysis
One short paragraph explaining your approach and key design decisions.

## Implementation
```python
# your complete code here
```

## Assumptions
Bullet list of any assumptions you made about the requirement."""

SYSTEM_A_REFINE = """You are Agent A — an expert Python software engineer.
You previously wrote code. Agent B (the debugger) reviewed it and found issues.
Your job is to fix EVERY issue Agent B raised and produce improved, final code.

Guidelines:
- Address each issue Agent B mentioned explicitly
- Write COMPLETE, runnable fixed code — not diffs or snippets
- Add/improve type hints, docstrings, error handling as needed
- Be concise in the "Changes Made" section

Response format (strictly follow this):
## Changes Made
Numbered list of every fix applied, mapped to Agent B's issues.

## Improved Implementation
```python
# your complete improved code here
```"""

SYSTEM_B_REVIEW = """You are Agent B — a meticulous Python code reviewer and debugger.
You receive code from Agent A and must critically review it across these dimensions:

1. **Correctness** — Logic errors, wrong algorithm, off-by-one, incorrect output
2. **Edge Cases** — Empty input, None, zero, negative numbers, large values, type mismatches
3. **Error Handling** — Missing try/except, uncaught exceptions, vague error messages
4. **Security** — unsafe eval/exec, shell injection, unvalidated input, hardcoded secrets
5. **Performance** — O(n²) where better exists, unnecessary memory allocation
6. **Code Quality** — PEP8, naming, dead code, non-Pythonic patterns

Response format (strictly follow this):
## Overall Verdict
[PASS ✓ | NEEDS WORK ⚠ | CRITICAL ISSUES ✗] — one sentence summary.

## Issues Found
Numbered list. Each item must include:
- **Category**: (Correctness / Edge Case / Error Handling / Security / Performance / Quality)
- **Problem**: specific description, reference line numbers or variable names
- **Impact**: why this matters

If no issues, write "No issues found — code is correct and well-written."

## Recommended Fixes
Concise, actionable instructions for Agent A to fix each issue."""

SYSTEM_B_FINAL = """You are Agent B — a meticulous Python code reviewer.
Agent A has revised the code based on your earlier feedback. Do a FINAL review.

Be fair: if the code is now correct and production-quality, say so clearly.
Only flag issues that are genuinely still present.

Response format (strictly follow this):
## Final Verdict
[PASS ✓ | STILL HAS ISSUES ⚠] — one confident sentence.

## Code Quality Summary
2-4 sentences on the overall quality, strengths, and remaining concerns (if any).

## Remaining Issues (if any)
Numbered list of only the critical unresolved problems. Omit this section on PASS."""


# ── Helpers ───────────────────────────────────────────────────────────────────
def call_agent(system_prompt: str, messages: list) -> str:
    """Call Groq API and return full response text."""
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "system", "content": system_prompt}] + messages,
        temperature=0.3,  # lower = more deterministic code
    )
    return response.choices[0].message.content


def sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run_agents():
    """Main endpoint: streams agent messages via SSE."""
    data = request.get_json()
    requirement = data.get("requirement", "").strip()
    num_rounds = int(data.get("rounds", 2))

    if not requirement:
        return {"error": "No requirement provided"}, 400

    def generate():
        try:
            a_code = ""
            b_feedback = ""

            for round_num in range(1, num_rounds + 1):

                # ── Agent A: Write / Refine ────────────────────────────────
                yield sse_event("status", {
                    "agent": "A",
                    "round": round_num,
                    "message": f"Round {round_num}: Agent A is {'writing initial code' if round_num == 1 else 'refining the code'}…"
                })

                if round_num == 1:
                    a_messages = [{"role": "user", "content": f"Write Python code for:\n\n{requirement}"}]
                    a_system = SYSTEM_A_INITIAL
                else:
                    a_messages = [{
                        "role": "user",
                        "content": (
                            f"Original requirement: {requirement}\n\n"
                            f"Your previous code:\n{a_code}\n\n"
                            f"Agent B's feedback:\n{b_feedback}\n\n"
                            "Fix all issues and produce the improved final version."
                        )
                    }]
                    a_system = SYSTEM_A_REFINE

                a_code = call_agent(a_system, a_messages)

                yield sse_event("agent_message", {
                    "agent": "A",
                    "round": round_num,
                    "round_label": f"Round {round_num} · {'Initial Draft' if round_num == 1 else 'Refined Code'}",
                    "content": a_code
                })

                # ── Agent B: Review ────────────────────────────────────────
                is_final_review = (round_num == num_rounds)

                yield sse_event("status", {
                    "agent": "B",
                    "round": round_num,
                    "message": f"Round {round_num}: Agent B is {'doing final review' if is_final_review else 'reviewing the code'}…"
                })

                if is_final_review and round_num > 1:
                    b_system = SYSTEM_B_FINAL
                    b_messages = [{
                        "role": "user",
                        "content": (
                            f"Requirement: {requirement}\n\n"
                            f"Original code:\n{a_code}\n\n"
                            f"Your earlier feedback:\n{b_feedback}\n\n"
                            f"Agent A's revised code:\n{a_code}\n\n"
                            "Do your final review."
                        )
                    }]
                else:
                    b_system = SYSTEM_B_REVIEW
                    b_messages = [{
                        "role": "user",
                        "content": (
                            f"Requirement: {requirement}\n\n"
                            f"Agent A's code:\n{a_code}\n\n"
                            "Review it carefully."
                        )
                    }]

                b_feedback = call_agent(b_system, b_messages)

                yield sse_event("agent_message", {
                    "agent": "B",
                    "round": round_num,
                    "round_label": f"Round {round_num} · {'Final Review' if is_final_review else 'Review'}",
                    "content": b_feedback
                })

            yield sse_event("done", {"rounds": num_rounds})

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
