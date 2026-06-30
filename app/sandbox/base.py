"""The sandbox contract.

A sandbox runs one command against one workspace under :class:`ResourceLimits`
and returns an :class:`ExecResult`. Two implementations exist: a Docker-backed
one (the real isolation boundary) and a local subprocess fallback for developer
machines without Docker, which is refused in any deployed environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from app.sandbox.models import ExecResult, ResourceLimits


@runtime_checkable
class Sandbox(Protocol):
    """Runs untrusted commands in isolation. Implementations must not leak
    secrets or host filesystem access beyond the mounted workspace."""

    def run(
        self,
        cmd: list[str],
        workspace: Path,
        limits: ResourceLimits | None = None,
    ) -> ExecResult:
        """Execute ``cmd`` with ``workspace`` as the working directory."""
        ...

    def mount_point(self, workspace: Path) -> str:
        """Where ``workspace`` appears *inside* the run environment.

        Frame paths in captured output are rooted here, so the runner uses it to
        relativize tracebacks. The local fallback runs in-place (the host path);
        Docker mounts at a fixed ``/workspace``.
        """
        ...
