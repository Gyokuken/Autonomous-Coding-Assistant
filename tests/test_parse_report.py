from dualcore.sandbox.base import parse_pytest_json


def test_all_passed():
    data = {"summary": {"passed": 3, "total": 3}, "tests": [
        {"nodeid": "t.py::a", "outcome": "passed"},
    ]}
    report = parse_pytest_json(data)
    assert report.parsed and report.all_passed
    assert report.passed == 3 and report.failed == 0


def test_failures_are_extracted():
    data = {
        "summary": {"passed": 1, "failed": 1, "total": 2},
        "tests": [
            {"nodeid": "t.py::ok", "outcome": "passed"},
            {
                "nodeid": "t.py::bad",
                "outcome": "failed",
                "call": {"outcome": "failed",
                         "crash": {"message": "assert 1 == 2"},
                         "longrepr": "E assert 1 == 2"},
            },
        ],
    }
    report = parse_pytest_json(data)
    assert not report.all_passed
    assert len(report.failures) == 1
    assert report.failures[0].message == "assert 1 == 2"


def test_collection_error_counts_as_failure():
    data = {"summary": {"total": 0}, "tests": [],
            "collectors": [{"nodeid": "t.py", "outcome": "failed",
                            "longrepr": "SyntaxError: bad"}]}
    report = parse_pytest_json(data)
    assert not report.all_passed
    assert report.errors >= 1
