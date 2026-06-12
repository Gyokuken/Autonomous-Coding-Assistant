"""Sandbox abstraction + result types shared by every driver.

A :class:`Sandbox` takes a set of in-memory files and a command, runs the command
in isolation, and returns a structured :class:`ExecutionResult`. When the command
is pytest (with the json-report plugin), the per-test breakdown is parsed into a
:class:`TestReport` so the orchestrator can reason about real pass/fail counts.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPORT_FILENAME = "report.json"


@dataclass
class TestCaseResult:
    """Outcome of a single test case."""

    name: str
    outcome: str  # "passed" | "failed" | "error" | "skipped"
    message: str = ""
    traceback: str = ""


@dataclass
class TestReport:
    """Aggregated, structured result of a pytest run."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    cases: list[TestCaseResult] = field(default_factory=list)
    parsed: bool = False  # True only when a JSON report was successfully read

    @property
    def all_passed(self) -> bool:
        return (
            self.parsed
            and self.total > 0
            and self.failed == 0
            and self.errors == 0
        )

    @property
    def failures(self) -> list[TestCaseResult]:
        return [c for c in self.cases if c.outcome in ("failed", "error")]

    def summary_line(self) -> str:
        if not self.parsed:
            return "no structured test report"
        return (
            f"{self.passed} passed, {self.failed} failed, "
            f"{self.errors} errors, {self.skipped} skipped (of {self.total})"
        )


@dataclass
class ExecutionResult:
    """Result of running a command inside a sandbox."""

    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    report: TestReport | None = None
    setup_error: str | None = None  # infra problem (daemon down, image missing…)

    @property
    def all_passed(self) -> bool:
        if self.setup_error or self.timed_out:
            return False
        if self.report is not None and self.report.parsed:
            return self.report.all_passed
        return self.ok


class Sandbox(ABC):
    """Runs untrusted code in isolation."""

    @abstractmethod
    def execute(
        self,
        files: Mapping[str, str],
        command: Sequence[str],
        *,
        timeout: int,
        profile: str = "basic",
    ) -> ExecutionResult:
        """Write ``files`` into an isolated workdir and run ``command`` there."""

    def health_check(self) -> tuple[bool, str]:
        """Return ``(ok, message)`` describing whether the driver can run."""
        return True, "ok"


# ── Shared helpers ──────────────────────────────────────────────────────────


def _safe_name(name: str) -> str:
    p = Path(name)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"unsafe filename: {name!r}")
    return str(p)


@contextlib.contextmanager
def materialize(files: Mapping[str, str]) -> Iterator[str]:
    """Write ``files`` to a fresh temp dir; clean it up on exit."""
    workdir = tempfile.mkdtemp(prefix="dualcore-")
    try:
        for name, content in files.items():
            path = Path(workdir) / _safe_name(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        yield workdir
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _longrepr_str(longrepr: object) -> str:
    if isinstance(longrepr, str):
        return longrepr
    if isinstance(longrepr, dict):
        crash = longrepr.get("reprcrash") or {}
        if isinstance(crash, dict) and crash.get("message"):
            return str(crash["message"])
        return json.dumps(longrepr)[:2000]
    return str(longrepr) if longrepr else ""


def parse_pytest_json(data: dict) -> TestReport:
    """Convert a pytest-json-report payload into a :class:`TestReport`."""
    summary = data.get("summary", {}) or {}
    report = TestReport(
        total=int(summary.get("total", summary.get("collected", 0)) or 0),
        passed=int(summary.get("passed", 0) or 0),
        failed=int(summary.get("failed", 0) or 0),
        errors=int(summary.get("error", 0) or 0),
        skipped=int(summary.get("skipped", 0) or 0),
        parsed=True,
    )

    for test in data.get("tests", []) or []:
        outcome = test.get("outcome", "")
        message, traceback = "", ""
        for stage in ("call", "setup", "teardown"):
            st = test.get(stage)
            if isinstance(st, dict) and st.get("outcome") in ("failed", "error"):
                crash = st.get("crash") or {}
                if isinstance(crash, dict):
                    message = str(crash.get("message", "")) or message
                traceback = _longrepr_str(st.get("longrepr", ""))
                break
        report.cases.append(
            TestCaseResult(
                name=test.get("nodeid", ""),
                outcome=outcome,
                message=message,
                traceback=traceback,
            )
        )

    # Collection errors (e.g. a SyntaxError in the code under test) show up here.
    failed_collectors = [
        c for c in (data.get("collectors", []) or []) if c.get("outcome") == "failed"
    ]
    for c in failed_collectors:
        report.cases.append(
            TestCaseResult(
                name=c.get("nodeid", "<collection>"),
                outcome="error",
                message="collection error",
                traceback=_longrepr_str(c.get("longrepr", "")),
            )
        )
    if failed_collectors and report.total == 0:
        report.errors = max(report.errors, len(failed_collectors))
        report.total = report.errors

    return report


def read_report(workdir: str) -> TestReport | None:
    """Read and parse ``report.json`` from ``workdir`` if present."""
    path = Path(workdir) / REPORT_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parse_pytest_json(data)
