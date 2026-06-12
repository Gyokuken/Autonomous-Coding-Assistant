"""Sandbox drivers and factory."""

from __future__ import annotations

from ..config import Settings
from .base import (
    ExecutionResult,
    Sandbox,
    TestCaseResult,
    TestReport,
    parse_pytest_json,
)
from .docker_sandbox import DockerSandbox
from .subprocess_sandbox import SubprocessSandbox

__all__ = [
    "ExecutionResult",
    "Sandbox",
    "TestCaseResult",
    "TestReport",
    "DockerSandbox",
    "SubprocessSandbox",
    "parse_pytest_json",
    "get_sandbox",
]


def get_sandbox(settings: Settings) -> Sandbox:
    """Return the sandbox driver selected by configuration."""
    if settings.sandbox_driver == "docker":
        return DockerSandbox(settings)
    return SubprocessSandbox(settings)
