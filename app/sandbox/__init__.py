"""Container lifecycle, resource caps, egress control, capability dropping,
workspace mounts (Phase 2+).

The isolation boundary. One ephemeral container per job; no secrets, no egress.
A local subprocess fallback exists for dev machines and is disabled when
``Settings.is_deployed``.

:func:`get_sandbox` picks the implementation: Docker when available, else the
local fallback — but never the fallback in a deployed environment.
"""

from __future__ import annotations

from app.core.settings import Settings, get_settings
from app.sandbox.base import Sandbox
from app.sandbox.docker import DockerNotFound, DockerSandbox, docker_available
from app.sandbox.local import LocalSandbox
from app.sandbox.models import ExecResult, ResourceLimits

__all__ = [
    "DockerNotFound",
    "DockerSandbox",
    "ExecResult",
    "LocalSandbox",
    "ResourceLimits",
    "Sandbox",
    "docker_available",
    "get_sandbox",
]


class SandboxUnavailable(RuntimeError):
    """Raised when no acceptable sandbox is available for the environment."""


def get_sandbox(
    settings: Settings | None = None,
    *,
    prefer_local: bool = False,
    image: str | None = None,
) -> Sandbox:
    """Return the appropriate sandbox for the current environment.

    Deployed environments (``ci``/``prod``) require Docker — the local fallback
    is never returned there. Locally, Docker is used when present, otherwise the
    subprocess fallback. ``prefer_local`` forces the fallback in local dev (useful
    for fast offline tests). ``image`` selects the per-language Docker base image
    (Phase 8); it is ignored by the local fallback, which runs against the host
    toolchain in-place.
    """
    settings = settings or get_settings()

    def _docker() -> Sandbox:
        return DockerSandbox(image) if image else DockerSandbox()

    if settings.is_deployed:
        if not docker_available():
            raise SandboxUnavailable(
                "a deployed environment requires Docker, but the docker CLI was not found"
            )
        return _docker()

    if prefer_local:
        return LocalSandbox()
    if docker_available():
        return _docker()
    return LocalSandbox()
