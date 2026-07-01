"""Docker-backed sandbox — the real isolation boundary.

One ``docker run`` per command against an ephemeral, non-root, network-isolated
container with CPU/memory/PID and wall-clock caps, a read-only rootfs, dropped
capabilities, and a single bind mount: the job workspace at ``/workspace``
(ARCHITECTURE.md §7). The container is named so it can be force-killed if the
wall clock expires, and ``--rm`` discards it regardless of outcome.

Invoked through the ``docker`` CLI via subprocess (matching the git-via-subprocess
pattern in :mod:`app.index.clone`) so no Docker SDK dependency is required.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from pathlib import Path

from app.sandbox.models import ExecResult, ResourceLimits

DEFAULT_IMAGE = "bugfix-sandbox:latest"
# Where the workspace volume is mounted inside every container.
WORKSPACE_MOUNT = "/workspace"
# Grace beyond the container's own timeout before we give up waiting on `docker run`.
_KILL_GRACE_S = 10.0


class DockerNotFound(RuntimeError):
    """Raised when the ``docker`` binary is not on PATH."""


def docker_available() -> bool:
    """True when a usable ``docker`` CLI is on PATH."""
    return shutil.which("docker") is not None


def image_available(image: str = DEFAULT_IMAGE) -> bool:
    """True when ``image`` is present locally (daemon up *and* image built).

    ``docker_available`` only checks the CLI is on PATH; a live container still
    fails with exit 125 if the daemon is down or the image was never built (as in
    CI). ``docker image inspect`` returns non-zero in either case, so this is the
    correct guard for docker-marked tests that actually run a container.
    """
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        result = subprocess.run(
            [docker, "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


class DockerSandbox:
    """Runs each command in a throwaway, locked-down container."""

    def __init__(self, image: str = DEFAULT_IMAGE) -> None:
        self._docker = shutil.which("docker")
        if self._docker is None:
            raise DockerNotFound("docker is required but was not found on PATH")
        self.image = image

    def mount_point(self, workspace: Path) -> str:
        """The workspace is bind-mounted at a fixed path inside the container."""
        return WORKSPACE_MOUNT

    def run(
        self,
        cmd: list[str],
        workspace: Path,
        limits: ResourceLimits | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        limits = limits or ResourceLimits()
        workspace = workspace.resolve()
        name = f"bugfix-{uuid.uuid4().hex[:12]}"

        run_cmd = self._build_run_cmd(name, cmd, workspace, limits, env)

        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                run_cmd,
                capture_output=True,
                text=True,
                # `docker run` should self-terminate at limits.timeout_s; give it
                # a little slack, then fall back to killing the container.
                timeout=limits.timeout_s + _KILL_GRACE_S,
                check=False,
            )
            returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = -1
            stdout = self._as_text(exc.stdout)
            stderr = self._as_text(exc.stderr)
            self._force_kill(name)
        duration = time.monotonic() - start

        return ExecResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            duration_s=duration,
            timed_out=timed_out,
        )

    def _build_run_cmd(
        self,
        name: str,
        cmd: list[str],
        workspace: Path,
        limits: ResourceLimits,
        env: dict[str, str] | None = None,
    ) -> list[str]:
        assert self._docker is not None
        run_cmd = [
            self._docker,
            "run",
            "--rm",
            "--name",
            name,
            "--cpus",
            str(limits.cpus),
            "--memory",
            limits.memory,
            # Disabling swap keeps the memory cap honest.
            "--memory-swap",
            limits.memory,
            "--pids-limit",
            str(limits.pids),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            # Tests need a scratch area; rootfs stays read-only.
            "--tmpfs",
            "/tmp:rw,size=256m",
            "--user",
            "10001:10001",
            "--workdir",
            WORKSPACE_MOUNT,
            "-v",
            f"{workspace}:{WORKSPACE_MOUNT}",
        ]
        for key, value in (env or {}).items():
            run_cmd += ["-e", f"{key}={value}"]
        if not limits.network:
            run_cmd += ["--network", "none"]
        # Bound the run from inside too, so a wedged container can't outlive us.
        run_cmd += ["--stop-timeout", str(int(limits.timeout_s))]
        run_cmd += [self.image, *cmd]
        return run_cmd

    def _force_kill(self, name: str) -> None:
        assert self._docker is not None
        subprocess.run(
            [self._docker, "kill", name],
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _as_text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        return value.decode(errors="replace") if isinstance(value, bytes) else value
