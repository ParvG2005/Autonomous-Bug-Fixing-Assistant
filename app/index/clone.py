"""Clone a repo into the workspace.

A deterministic service (ARCHITECTURE.md §4). Shallow by default to keep clones
cheap. In the deployed system the control plane streams the repo into the
sandbox volume; this helper covers local dev + the Phase 1 CLI. Accepts a remote
URL or a local path (handy for fixtures and offline tests).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_GIT = shutil.which("git")


class GitNotFound(RuntimeError):
    """Raised when the ``git`` binary is not on PATH."""


def clone_repo(source: str, dest: Path, *, depth: int = 1, ref: str | None = None) -> Path:
    """Clone ``source`` into ``dest`` and return the workspace path.

    Args:
        source: a git URL or a local filesystem path.
        dest: target directory (must not already exist and be non-empty).
        depth: shallow-clone depth; ``0`` disables shallowness.
        ref: optional branch/tag/commit to check out.
    """
    if _GIT is None:
        raise GitNotFound("git is required to clone but was not found on PATH")
    dest = dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"destination {dest} already exists and is not empty")
    dest.parent.mkdir(parents=True, exist_ok=True)

    cmd = [_GIT, "clone"]
    if depth:
        cmd += ["--depth", str(depth)]
    if ref:
        cmd += ["--branch", ref]
    cmd += ["--", source, str(dest)]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed: {proc.stderr.strip()}")
    return dest
