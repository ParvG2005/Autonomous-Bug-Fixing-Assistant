"""The local subprocess sandbox + get_sandbox selection logic."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core.settings import Settings
from app.sandbox import (
    LocalSandbox,
    ResourceLimits,
    SandboxUnavailable,
    docker_available,
    get_sandbox,
)


def test_runs_command_and_captures_output(tmp_path: Path) -> None:
    result = LocalSandbox().run([sys.executable, "-c", "print('hello')"], tmp_path)
    assert result.ok
    assert "hello" in result.stdout


def test_uses_workspace_as_cwd(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    result = LocalSandbox().run(
        [sys.executable, "-c", "import os; print(os.listdir('.'))"], tmp_path
    )
    assert "marker.txt" in result.stdout


def test_nonzero_exit_is_not_ok(tmp_path: Path) -> None:
    result = LocalSandbox().run([sys.executable, "-c", "raise SystemExit(3)"], tmp_path)
    assert result.returncode == 3
    assert not result.ok


def test_timeout_is_flagged(tmp_path: Path) -> None:
    limits = ResourceLimits(timeout_s=0.5)
    result = LocalSandbox().run(
        [sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, limits
    )
    assert result.timed_out
    assert not result.ok


def test_get_sandbox_local_when_forced() -> None:
    assert isinstance(get_sandbox(prefer_local=True), LocalSandbox)


def test_get_sandbox_refuses_local_when_deployed_without_docker() -> None:
    settings = Settings(app_env="prod")
    if docker_available():
        pytest.skip("docker present; the deployed path returns a DockerSandbox")
    with pytest.raises(SandboxUnavailable):
        get_sandbox(settings)
