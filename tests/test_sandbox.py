from dualcore.config import Settings
from dualcore.orchestrator import PYTEST_CMD
from dualcore.sandbox.subprocess_sandbox import SubprocessSandbox

SOLUTION = "def add(a, b):\n    return a + b\n"


def _sandbox():
    return SubprocessSandbox(Settings(groq_api_key="", sandbox_driver="subprocess"))


def test_passing_suite():
    tests = "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    result = _sandbox().execute(
        {"solution.py": SOLUTION, "test_solution.py": tests}, PYTEST_CMD, timeout=30
    )
    assert result.all_passed
    assert result.report.passed == 1


def test_failing_suite_reports_failure():
    tests = "from solution import add\n\ndef test_add():\n    assert add(2, 3) == 99\n"
    result = _sandbox().execute(
        {"solution.py": SOLUTION, "test_solution.py": tests}, PYTEST_CMD, timeout=30
    )
    assert not result.all_passed
    assert result.report.failed == 1


def test_syntax_error_is_a_collection_error():
    tests = "from solution import add\n\ndef test_oops(\n    assert True\n"
    result = _sandbox().execute(
        {"solution.py": SOLUTION, "test_solution.py": tests}, PYTEST_CMD, timeout=30
    )
    assert not result.all_passed
    assert result.report.errors >= 1


def test_env_is_scrubbed_of_secrets(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "super-secret")
    leak = (
        "import os\n\n"
        "def test_no_secret():\n"
        "    assert os.environ.get('GROQ_API_KEY') is None\n"
    )
    result = _sandbox().execute(
        {"solution.py": SOLUTION, "test_solution.py": leak}, PYTEST_CMD, timeout=30
    )
    assert result.all_passed, "child process should not see GROQ_API_KEY"
