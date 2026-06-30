"""Test-framework detection across common layouts."""

from __future__ import annotations

from pathlib import Path

from app.runner.detect import detect_framework
from app.runner.models import Framework


def test_detects_pytest_from_test_files(failing_project: Path) -> None:
    assert detect_framework(failing_project) is Framework.PYTEST


def test_detects_pytest_from_pyproject_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8"
    )
    assert detect_framework(tmp_path) is Framework.PYTEST


def test_detects_pytest_from_pytest_ini(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    assert detect_framework(tmp_path) is Framework.PYTEST


def test_no_framework_in_empty_workspace(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    assert detect_framework(tmp_path) is None


def test_ignores_tests_inside_vendored_dirs(tmp_path: Path) -> None:
    vendored = tmp_path / ".venv" / "lib"
    vendored.mkdir(parents=True)
    (vendored / "test_vendored.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    assert detect_framework(tmp_path) is None
