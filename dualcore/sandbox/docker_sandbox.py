"""Docker sandbox — the production driver.

Each execution runs in a throwaway container with no network, dropped Linux
capabilities, a read-only root filesystem, and memory/CPU/pid caps. The only
writable surface is the ephemeral bind-mounted workdir (and a small /tmp tmpfs).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping, Sequence
from uuid import uuid4

from ..config import Settings
from .base import ExecutionResult, Sandbox, materialize, read_report


class DockerSandbox(Sandbox):
    """Runs code inside a hardened, ephemeral Docker container."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def health_check(self) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except FileNotFoundError:
            return False, "Docker CLI not found on PATH."
        except subprocess.TimeoutExpired:
            return False, "Docker did not respond (is the daemon starting?)."
        if result.returncode != 0:
            return False, "Docker daemon not reachable. Start Docker Desktop."
        return True, f"docker {result.stdout.strip()}"

    def _image_exists(self, image: str) -> bool:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def _docker_args(self, name: str, image: str, workdir: str) -> list[str]:
        s = self._settings
        return [
            "docker", "run", "--rm", "--name", name,
            "--network", "none",
            f"--memory={s.mem_limit_mb}m",
            f"--memory-swap={s.mem_limit_mb}m",
            f"--cpus={s.cpu_limit}",
            f"--pids-limit={s.pids_limit}",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:rw,exec,size=128m",
            "-e", "HOME=/tmp",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "PYTHONIOENCODING=utf-8",
            "-v", f"{workdir}:/work",
            "-w", "/work",
            image,
        ]

    def execute(
        self,
        files: Mapping[str, str],
        command: Sequence[str],
        *,
        timeout: int,
        profile: str = "basic",
    ) -> ExecutionResult:
        ok, message = self.health_check()
        if not ok:
            return _setup_error(message)

        image = self._settings.image_for(profile)
        if not self._image_exists(image):
            return _setup_error(
                f"Sandbox image {image!r} not found. Build it with: "
                f"python scripts/build_sandbox_images.py"
            )

        with materialize(files) as workdir:
            name = f"dualcore-{uuid4().hex[:12]}"
            args = self._docker_args(name, image, workdir) + list(command)
            start = time.monotonic()
            timed_out = False
            try:
                # +5s grace so docker's own startup isn't counted against the job.
                result = subprocess.run(
                    args, capture_output=True, text=True, timeout=timeout + 5, check=False
                )
                out, err, code = result.stdout, result.stderr, result.returncode
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                subprocess.run(["docker", "kill", name], capture_output=True, check=False)
                out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                code = -1

            duration = time.monotonic() - start
            return ExecutionResult(
                ok=(code == 0 and not timed_out),
                exit_code=code,
                stdout=out or "",
                stderr=err or "",
                duration_s=duration,
                timed_out=timed_out,
                report=read_report(workdir),
            )


def _setup_error(message: str) -> ExecutionResult:
    return ExecutionResult(
        ok=False, exit_code=-1, stdout="", stderr=message, duration_s=0.0,
        setup_error=message,
    )
