"""Phase 2 acceptance inside the real Docker sandbox.

Builds the sandbox image and runs the known-failing project in a capped,
network-isolated, non-root container, asserting the same structured frames the
local path produces. Marked ``docker`` + ``integration`` so the default unit run
stays fast and offline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.runner import Outcome, run_pytest
from app.sandbox import ResourceLimits, docker_available
from app.sandbox.docker import DEFAULT_IMAGE, DockerSandbox

pytestmark = [pytest.mark.integration, pytest.mark.docker]

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def sandbox_image() -> str:
    if not docker_available():
        pytest.skip("docker CLI not available")
    build = subprocess.run(
        [
            "docker",
            "build",
            "-t",
            DEFAULT_IMAGE,
            "-f",
            str(_REPO_ROOT / "docker" / "sandbox.Dockerfile"),
            str(_REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if build.returncode != 0:
        pytest.skip(f"sandbox image build failed: {build.stderr[-500:]}")
    return DEFAULT_IMAGE


def test_pytest_runs_in_container(failing_project: Path, sandbox_image: str) -> None:
    sandbox = DockerSandbox(image=sandbox_image)
    result = run_pytest(
        failing_project,
        sandbox,
        limits=ResourceLimits(timeout_s=120.0),
    )

    assert result.outcome is Outcome.FAILED
    assert result.passed == 1
    assert result.failed == 2

    by_id = {f.nodeid.split("::")[-1]: f for f in result.failures}
    zero = by_id["test_divide_by_zero"]
    inner = zero.innermost_frame
    assert inner is not None
    assert inner.file == "calc.py"
    assert inner.function == "divide"


def test_container_has_no_network(failing_project: Path, sandbox_image: str) -> None:
    sandbox = DockerSandbox(image=sandbox_image)
    # python -c that tries to open a socket to a public IP; egress is off so it
    # must fail (non-zero) rather than connect.
    result = sandbox.run(
        [
            "python",
            "-c",
            "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)",
        ],
        failing_project,
        ResourceLimits(timeout_s=15.0),
    )
    assert result.returncode != 0
