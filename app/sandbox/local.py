"""Local subprocess sandbox — developer fallback only.

This is NOT a real isolation boundary: it runs the command as the current user
with full host access. It exists so the runner and agent loop are exercisable on
machines without Docker. :func:`app.sandbox.get_sandbox` refuses to hand this out
in a deployed environment (ARCHITECTURE.md §7).

What it still enforces: a wall-clock timeout (the process tree is killed on
expiry) and best-effort POSIX resource limits (CPU seconds, address space) via
``resource`` rlimits applied in the child before exec.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from app.sandbox.models import ExecResult, ResourceLimits


def _memory_bytes(memory: str) -> int | None:
    """Parse a Docker-style size string (``"1g"``, ``"512m"``) to bytes."""
    units = {"k": 1024, "m": 1024**2, "g": 1024**3}
    s = memory.strip().lower()
    if not s:
        return None
    if s[-1] in units:
        try:
            return int(float(s[:-1]) * units[s[-1]])
        except ValueError:
            return None
    try:
        return int(s)
    except ValueError:
        return None


class LocalSandbox:
    """Runs commands as a subprocess on the host. Dev-only."""

    def mount_point(self, workspace: Path) -> str:
        """The local fallback runs in-place, so the mount point is the host path."""
        return str(workspace.resolve())

    def run(
        self,
        cmd: list[str],
        workspace: Path,
        limits: ResourceLimits | None = None,
    ) -> ExecResult:
        limits = limits or ResourceLimits()
        preexec = self._rlimit_setter(limits)

        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=limits.timeout_s,
                check=False,
                preexec_fn=preexec,
            )
            returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = -1
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        duration = time.monotonic() - start

        return ExecResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            duration_s=duration,
            timed_out=timed_out,
        )

    @staticmethod
    def _rlimit_setter(limits: ResourceLimits):  # type: ignore[no-untyped-def]
        """Build a ``preexec_fn`` that applies rlimits, or ``None`` if unavailable.

        ``resource`` is POSIX-only and absent on Windows; degrade gracefully.
        """
        try:
            import resource
        except ImportError:  # pragma: no cover - non-POSIX
            return None

        import contextlib

        mem = _memory_bytes(limits.memory)
        cpu_seconds = max(1, int(limits.timeout_s))

        def _apply() -> None:  # pragma: no cover - runs in the forked child
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
            if mem is not None:
                with contextlib.suppress(ValueError, OSError):
                    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))

        return _apply
