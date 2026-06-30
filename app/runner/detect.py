"""Test-framework detection.

Decides whether a workspace uses pytest, using the same signals pytest itself
keys on plus the conventional layout: a ``[tool.pytest.ini_options]`` table,
``pytest.ini``/``tox.ini``/``setup.cfg`` config, a ``conftest.py``, or
``test_*.py`` / ``*_test.py`` files anywhere in the tree.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from app.runner.models import Framework

# Directories that never hold a project's own tests; skip them when scanning so a
# vendored dependency's tests don't trigger a false positive.
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", "build", "dist"}


def _has_pytest_config(workspace: Path) -> bool:
    if (workspace / "pytest.ini").is_file() or (workspace / "conftest.py").is_file():
        return True

    pyproject = workspace / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        if "pytest" in data.get("tool", {}):
            return True

    for name, section in (("tox.ini", "[pytest]"), ("setup.cfg", "[tool:pytest]")):
        cfg = workspace / name
        if cfg.is_file():
            try:
                if section in cfg.read_text(encoding="utf-8"):
                    return True
            except OSError:
                continue
    return False


def _has_test_files(workspace: Path) -> bool:
    for path in workspace.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        name = path.name
        if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
            return True
    return False


def detect_framework(workspace: Path) -> Framework | None:
    """Return the test framework in ``workspace``, or ``None`` if none is found."""
    workspace = workspace.resolve()
    if not workspace.is_dir():
        return None
    if _has_pytest_config(workspace) or _has_test_files(workspace):
        return Framework.PYTEST
    return None
