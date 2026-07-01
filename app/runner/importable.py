"""Make a cloned repo importable in the network-off sandbox (P2).

The sandbox clones a repo into a job-id directory and ships only the test
framework — no editable install, no network. Two common layouts then fail to
import even though the code is fine:

1. **src layout** — ``src/pkg/__init__.py`` with tests doing ``import pkg``. Fix:
   put ``src`` on ``PYTHONPATH``.
2. **root-is-a-package under an alias** — the repo's files live at its root
   (``__init__.py`` at the top) and tests import it by a name that differs from
   the clone directory, e.g. ``from calibrate import bands`` where the clone dir
   is ``<job-id>``. There is no ``calibrate`` directory, so the import dies at
   collection. Fix: write a real *shim* package ``.bugfix_import/<pkg>/`` whose
   ``__path__`` is re-rooted to the repo, and put ``.bugfix_import`` on the path.

A shim (real files) is used rather than a symlink because a symlinked directory
would make ``Path.rglob`` (used by framework detection and the symbol index)
recurse forever; and it lives *inside* the workspace so it is visible through the
Docker bind mount, unlike a sibling directory.

:func:`ensure_importable` returns PYTHONPATH segments **relative to the
workspace** (``""`` denotes the workspace root itself), so the caller can map
them onto wherever the sandbox mounts the workspace.
"""

from __future__ import annotations

import re
from pathlib import Path

# Directory (inside the workspace) that holds generated import shims.
IMPORT_ROOT = ".bugfix_import"

_TEST_GLOBS = ("test_*.py", "*_test.py", "conftest.py")
# `from NAME import a, b` — capture the top-level module and the imported names.
_FROM_RE = re.compile(r"^\s*from\s+([A-Za-z_]\w*)(?:\.\w+)*\s+import\s+(.+?)(?:#.*)?$")

_SHIM = '''\
"""Auto-generated import shim (bugfix-assistant): re-roots this package to the repo root."""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
_root = _os.path.abspath(_os.path.join(_here, _os.pardir, _os.pardir))
__path__ = [_root]
_real_init = _os.path.join(_root, "__init__.py")
if _os.path.isfile(_real_init):
    __file__ = _real_init
    with open(_real_init, encoding="utf-8") as _f:
        exec(compile(_f.read(), _real_init, "exec"))  # noqa: S102
'''


def _importable_at_root(workspace: Path, name: str) -> bool:
    """True if ``import name`` already resolves against the workspace root."""
    return (workspace / name).is_dir() or (workspace / f"{name}.py").is_file()


def _exists_at_root(workspace: Path, name: str) -> bool:
    return (workspace / f"{name}.py").is_file() or (workspace / name).is_dir()


def _infer_alias(workspace: Path) -> str | None:
    """Infer the import name a root-level package is expected to be reached by.

    Only fires when the repo root is itself a package (``__init__.py`` present).
    Looks for a test import ``from PKG import X`` where ``PKG`` is not importable
    as-is but ``X`` is a module/subpackage that lives at the repo root — the
    signature of "the whole repo is package ``PKG``".
    """
    if not (workspace / "__init__.py").is_file():
        return None

    for pattern in _TEST_GLOBS:
        for test_file in sorted(workspace.rglob(pattern)):
            if IMPORT_ROOT in test_file.parts:
                continue
            try:
                lines = test_file.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                m = _FROM_RE.match(line)
                if m is None:
                    continue
                pkg, imported = m.group(1), m.group(2)
                if _importable_at_root(workspace, pkg):
                    continue
                names = [n.strip().split(" as ")[0].strip() for n in imported.split(",")]
                if any(name and _exists_at_root(workspace, name) for name in names):
                    return pkg
    return None


def ensure_importable(workspace: Path) -> list[str]:
    """Prepare ``workspace`` for import and return PYTHONPATH segments.

    Segments are relative to the workspace root; ``""`` denotes the root itself.
    May write a shim package under ``.bugfix_import`` as a side effect.
    """
    segments: list[str] = [""]

    if (workspace / "src").is_dir():
        segments.append("src")

    alias = _infer_alias(workspace)
    if alias is not None:
        shim_pkg = workspace / IMPORT_ROOT / alias
        shim_pkg.mkdir(parents=True, exist_ok=True)
        (shim_pkg / "__init__.py").write_text(_SHIM, encoding="utf-8")
        if IMPORT_ROOT not in segments:
            segments.append(IMPORT_ROOT)

    return segments
