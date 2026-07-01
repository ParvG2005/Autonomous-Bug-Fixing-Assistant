"""Make a cloned repo importable in the sandbox before tests run (P2).

``ensure_importable`` fixes the two layouts the bare sandbox breaks on without a
network or an editable install: a ``src/`` layout, and a repo that is itself a
package imported under a name that differs from the clone directory (files at the
repo root, tests doing ``from <pkg> import ...``). It returns PYTHONPATH segments
(relative to the workspace) and, for the alias case, writes a real shim package.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.runner.importable import ensure_importable


def _pythonpath(workspace: Path, segments: list[str]) -> str:
    return os.pathsep.join(str(workspace / s) if s else str(workspace) for s in segments)


def _can_import(
    workspace: Path, segments: list[str], stmt: str
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": _pythonpath(workspace, segments)}
    return subprocess.run(
        [sys.executable, "-c", stmt],
        cwd=str(workspace),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_root_package_alias_makes_import_work(tmp_path: Path) -> None:
    # A "Workflow"-shaped repo: files at root, __init__.py at root, tests import
    # the package by a name ("calibrate") that is not the clone dir name.
    (tmp_path / "__init__.py").write_text('"""calibrate pkg."""\n', encoding="utf-8")
    (tmp_path / "bands.py").write_text("def ordering_ok():\n    return True\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "from calibrate import bands\n\n\ndef test_o():\n    assert bands.ordering_ok()\n",
        encoding="utf-8",
    )

    segments = ensure_importable(tmp_path)

    # A real shim package was written (no symlink -> no rglob recursion).
    shim = tmp_path / ".bugfix_import" / "calibrate" / "__init__.py"
    assert shim.is_file()
    assert not shim.parent.is_symlink()
    # And the package genuinely imports with the returned PYTHONPATH.
    proc = _can_import(
        tmp_path, segments, "from calibrate import bands; print(bands.ordering_ok())"
    )
    assert proc.returncode == 0, proc.stderr
    assert "True" in proc.stdout


def test_src_layout_is_added_to_path(tmp_path: Path) -> None:
    src = tmp_path / "src" / "mypkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")

    segments = ensure_importable(tmp_path)

    assert "src" in segments
    proc = _can_import(tmp_path, segments, "import mypkg; print(mypkg.VALUE)")
    assert proc.returncode == 0, proc.stderr
    assert "42" in proc.stdout


def test_no_shim_when_already_importable(tmp_path: Path) -> None:
    # A conventional flat package (dir name == import name) needs no shim.
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "test_x.py").write_text("import mypkg\n", encoding="utf-8")

    ensure_importable(tmp_path)

    assert not (tmp_path / ".bugfix_import").exists()
