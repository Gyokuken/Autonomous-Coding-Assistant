"""Local subprocess sandbox — the dev driver.

This is *not* strong isolation: code runs as the same OS user as the app. The
mitigations here (allowlisted environment so the Groq key can't leak, isolated
temp workdir, wall-clock timeout with process-tree kill) make it safe enough for
trusted local use. **Do not expose this driver on a public deployment** — use the
Docker driver for that.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence

from ..config import Settings
from .base import ExecutionResult, Sandbox, materialize, read_report

# Only these environment variables are passed to the child. Notably absent:
# GROQ_API_KEY and anything else in the parent process.
_ENV_ALLOWLIST = (
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL",
    "HOME", "HOMEPATH", "HOMEDRIVE", "USERPROFILE", "SystemDrive",
    # Needed on Windows so the interpreter can locate user site-packages
    # (where pytest may be installed).
    "APPDATA", "LOCALAPPDATA",
)


def _resolve_command(command: Sequence[str]) -> list[str]:
    """Run the *same* interpreter as the app for ``python``/``python3``."""
    cmd = list(command)
    if cmd and cmd[0] in ("python", "python3"):
        cmd[0] = sys.executable
    return cmd


def _scrubbed_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("GROQ_API_KEY", None)  # belt and suspenders
    return env


def _new_process_group() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class SubprocessSandbox(Sandbox):
    """Runs code in a child process on the host."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def execute(
        self,
        files: Mapping[str, str],
        command: Sequence[str],
        *,
        timeout: int,
        profile: str = "basic",
    ) -> ExecutionResult:
        with materialize(files) as workdir:
            start = time.monotonic()
            timed_out = False
            try:
                proc = subprocess.Popen(
                    _resolve_command(command),
                    cwd=workdir,
                    env=_scrubbed_env(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    **_new_process_group(),
                )
            except FileNotFoundError as exc:
                return ExecutionResult(
                    ok=False,
                    exit_code=-1,
                    stdout="",
                    stderr=str(exc),
                    duration_s=0.0,
                    setup_error=f"Command not found: {command[0]!r}. "
                    "Is Python/pytest on PATH?",
                )

            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(proc)
                try:
                    out, err = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    out, err = "", ""

            duration = time.monotonic() - start
            code = proc.returncode if proc.returncode is not None else -1
            return ExecutionResult(
                ok=(code == 0 and not timed_out),
                exit_code=code,
                stdout=out or "",
                stderr=err or "",
                duration_s=duration,
                timed_out=timed_out,
                report=read_report(workdir),
            )
