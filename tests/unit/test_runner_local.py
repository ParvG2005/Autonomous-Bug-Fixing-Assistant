"""End-to-end Phase 2 acceptance via the local sandbox (no Docker required).

Runs a known-failing project through the real runner pipeline — detect → execute
→ parse — and asserts structured failure output with correct frames.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.runner import Outcome, run_pytest
from app.runner.pytest_runner import NoTestFramework
from app.sandbox import LocalSandbox, ResourceLimits


def test_run_pytest_produces_structured_failures(failing_project: Path) -> None:
    result = run_pytest(
        failing_project,
        LocalSandbox(),
        limits=ResourceLimits(timeout_s=60.0),
    )

    assert result.outcome is Outcome.FAILED
    assert result.passed == 1
    assert result.failed == 2

    by_id = {f.nodeid.split("::")[-1]: f for f in result.failures}
    assert set(by_id) == {"test_divide_by_zero", "test_add_wrong"}

    # The cross-frame failure localizes into calc.divide (workspace-relative).
    zero = by_id["test_divide_by_zero"]
    assert "ZeroDivisionError" in zero.message
    inner = zero.innermost_frame
    assert inner is not None
    assert inner.file == "calc.py"
    assert inner.function == "divide"


def test_run_pytest_all_pass(tmp_path: Path) -> None:
    (tmp_path / "test_ok.py").write_text(
        "def test_truth():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    result = run_pytest(tmp_path, LocalSandbox())
    assert result.outcome is Outcome.PASSED
    assert result.ok
    assert result.passed == 1


def test_run_pytest_raises_without_framework(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    with pytest.raises(NoTestFramework):
        run_pytest(tmp_path, LocalSandbox())


def test_local_sandbox_passes_env(tmp_path: Path) -> None:
    result = LocalSandbox().run(
        ["python", "-c", "import os; print(os.environ.get('BUGFIX_MARKER', 'unset'))"],
        tmp_path,
        env={"BUGFIX_MARKER": "on"},
    )
    assert result.returncode == 0
    assert "on" in result.stdout


def test_run_pytest_makes_root_package_importable(tmp_path: Path) -> None:
    # A "Workflow"-shaped repo (files at root, imported under an alias) must now
    # collect and run its tests instead of erroring at import.
    (tmp_path / "__init__.py").write_text('"""pkg."""\n', encoding="utf-8")
    (tmp_path / "bands.py").write_text("def ok():\n    return True\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "from calibrate import bands\n\n\ndef test_o():\n    assert bands.ok()\n",
        encoding="utf-8",
    )
    result = run_pytest(tmp_path, LocalSandbox())
    assert result.outcome is Outcome.PASSED, result.stdout + result.stderr
    assert result.passed == 1
