"""C2 — Sandboxed execution; §5 categories 2 (egress), 3 (fs escape), 4 (exhaustion).

The offline tests prove the container is *constructed* locked-down (the exact
``docker run`` flags) and that the deployed env refuses the unsafe local fallback.
The ``docker``-marked tests prove it *behaves* locked-down on a live daemon:
egress blocked, rootfs read-only, resource caps kill the job not the host, and the
container is gone afterwards.
"""

from __future__ import annotations

import pytest

from app.core.settings import Settings
from app.sandbox import (
    DockerSandbox,
    LocalSandbox,
    ResourceLimits,
    SandboxUnavailable,
    docker_available,
    get_sandbox,
)

pytestmark = pytest.mark.redteam


# --- construction-time hardening (offline) ------------------------------------


def _run_cmd(network: bool = False) -> list[str]:
    sandbox = DockerSandbox.__new__(DockerSandbox)  # bypass docker-on-PATH check
    sandbox._docker = "docker"  # type: ignore[attr-defined]
    sandbox.image = "img"  # type: ignore[attr-defined]
    from pathlib import Path

    return sandbox._build_run_cmd(  # type: ignore[attr-defined]
        "name", ["pytest"], Path("/ws"), ResourceLimits(network=network)
    )


def test_default_limits_have_no_egress() -> None:
    assert ResourceLimits().network is False


def test_docker_run_is_locked_down() -> None:
    cmd = " ".join(_run_cmd())
    assert "--network none" in cmd  # egress off
    assert "--cap-drop ALL" in cmd  # no capabilities
    assert "--security-opt no-new-privileges" in cmd  # no setuid escalation
    assert "--read-only" in cmd  # rootfs read-only
    assert "--user 10001:10001" in cmd  # non-root
    assert "--pids-limit" in cmd  # fork-bomb cap
    assert "--memory 1g" in cmd and "--memory-swap 1g" in cmd  # OOM cap, swap off
    assert "--rm" in cmd  # ephemeral: discarded regardless of outcome


def test_no_host_mount_beyond_workspace() -> None:
    cmd = _run_cmd()
    mounts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-v"]
    assert mounts == ["/ws:/workspace"]  # the single workspace bind, nothing else


def test_network_opt_in_is_explicit() -> None:
    assert "--network none" not in " ".join(_run_cmd(network=True))


# --- the deployed env must never hand out the unsafe local fallback -----------


def test_deployed_env_refuses_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.sandbox.docker_available", lambda: False)
    for env in ("ci", "prod"):
        with pytest.raises(SandboxUnavailable):
            get_sandbox(Settings(app_env=env))  # type: ignore[arg-type]


def test_local_dev_falls_back_only_off_deploy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.sandbox.docker_available", lambda: False)
    assert isinstance(get_sandbox(Settings(app_env="local")), LocalSandbox)


# --- live container behaviour (requires Docker) -------------------------------

_needs_docker = pytest.mark.skipif(not docker_available(), reason="requires Docker daemon")


@pytest.mark.docker
@_needs_docker
def test_live_egress_is_blocked(tmp_path) -> None:  # type: ignore[no-untyped-def]
    code = (
        "import socket,sys\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1',53),timeout=3); sys.exit(0)\n"
        "except OSError:\n"
        "    sys.exit(42)\n"
    )
    res = DockerSandbox().run(["python", "-c", code], tmp_path, ResourceLimits(timeout_s=30))
    assert res.returncode == 42  # connection refused/unreachable: no egress


@pytest.mark.docker
@_needs_docker
def test_live_rootfs_is_read_only(tmp_path) -> None:  # type: ignore[no-untyped-def]
    res = DockerSandbox().run(
        ["python", "-c", "open('/escape','w')"], tmp_path, ResourceLimits(timeout_s=30)
    )
    assert res.returncode != 0  # write outside workspace fails


@pytest.mark.docker
@_needs_docker
def test_live_pid_cap_contains_fork_bomb(tmp_path) -> None:  # type: ignore[no-untyped-def]
    code = "import os\nwhile True:\n    os.fork()\n"
    res = DockerSandbox().run(
        ["python", "-c", code], tmp_path, ResourceLimits(pids=64, timeout_s=20)
    )
    # The cap (or the wall clock) stops it; the host is unaffected — we got here.
    assert res.returncode != 0 or res.timed_out
