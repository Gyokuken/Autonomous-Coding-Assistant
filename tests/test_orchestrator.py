"""End-to-end orchestrator tests with a fake LLM and the real subprocess sandbox."""

from dualcore.config import Settings
from dualcore.orchestrator import Orchestrator
from dualcore.sandbox import get_sandbox

BUGGY = "## Implementation\n```python\ndef add(a, b):\n    return a - b\n```"
FIXED = "## Implementation\n```python\ndef add(a, b):\n    return a + b\n```"
TESTS = ("## Test Suite\n```python\nfrom solution import add\n\n"
         "def test_a():\n    assert add(2, 3) == 5\n```")
REVIEW = "## Final Verdict\nPASS"


class FakeLLM:
    """Returns canned responses based on which agent (system prompt) is calling."""

    def complete(self, system, messages, **kw):
        return "".join(self.stream(system, messages, **kw))

    def stream(self, system, messages, **kw):
        if "Test Designer" in system:
            yield TESTS
        elif "fixing your own code" in system:
            yield FIXED
        elif "review mode" in system:
            yield REVIEW
        else:
            yield BUGGY


def _run(llm, rounds):
    settings = Settings(groq_api_key="x", sandbox_driver="subprocess", max_rounds=4)
    orch = Orchestrator(llm, get_sandbox(settings), settings)
    return list(orch.run("add a and b", "", "basic", rounds))


def test_loop_fixes_bug_then_passes():
    events = _run(FakeLLM(), rounds=2)
    execs = [e for e in events if e["type"] == "execution"]
    done = [e for e in events if e["type"] == "done"]
    assert len(execs) == 2
    assert execs[0]["result"]["all_passed"] is False
    assert execs[1]["result"]["all_passed"] is True
    assert done and done[0]["passed"] is True


def test_streams_tokens_and_all_three_lanes():
    events = _run(FakeLLM(), rounds=1)
    assert any(e["type"] == "token" for e in events)
    lanes = {e["lane"] for e in events if e["type"] == "message"}
    assert {"coder", "tester", "reviewer"} <= lanes


def test_early_exit_when_first_attempt_passes():
    class GoodLLM(FakeLLM):
        def stream(self, system, messages, **kw):
            if "Test Designer" in system:
                yield TESTS
            elif "review mode" in system:
                yield REVIEW
            else:
                yield FIXED  # correct on the first try

    events = _run(GoodLLM(), rounds=3)
    execs = [e for e in events if e["type"] == "execution"]
    assert len(execs) == 1  # green on round 1 → no wasted rounds
