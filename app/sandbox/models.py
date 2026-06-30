"""Value types for the sandbox isolation boundary.

Resource caps and the shape of an execution result. Kept dependency-free so the
runner and agent tools can import them without pulling in Docker.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceLimits:
    """Caps applied to a single sandboxed command.

    Defaults are conservative: one CPU, 1 GiB memory, no network egress, and a
    two-minute wall-clock budget. See ARCHITECTURE.md §7 (sandbox model).
    """

    cpus: float = 1.0
    memory: str = "1g"
    pids: int = 256
    timeout_s: float = 120.0
    # Network egress is off by default; only a deliberate opt-in turns it on.
    network: bool = False


@dataclass(frozen=True)
class ExecResult:
    """Outcome of running a command inside a sandbox.

    ``stdout``/``stderr`` are captured text. ``timed_out`` is set when the wall
    clock exceeded :attr:`ResourceLimits.timeout_s`; in that case ``returncode``
    is whatever the killed process reported (often non-zero / negative).
    """

    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """True when the command exited cleanly (zero, not timed out)."""
        return self.returncode == 0 and not self.timed_out
