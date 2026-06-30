"""Lexical search over a workspace.

Shells out to ``rg --json`` when ripgrep is available so we get exact
byte/column offsets and respect the repo's ignore files — ripgrep is the
primary retrieval path (fast, exact). When ``rg`` is not on PATH the search
degrades to an equivalent pure-Python scan so the repo brain stays portable
(dev machines, minimal CI images).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

from app.index.models import Location, SearchHit

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache"}


def _rg_binary() -> str | None:
    """Locate a real ripgrep binary (resolved each call; PATH can change)."""
    return shutil.which("rg")


def search(
    pattern: str,
    root: Path,
    *,
    word: bool = False,
    fixed: bool = False,
    globs: Iterable[str] | None = None,
    max_count: int | None = None,
) -> list[SearchHit]:
    """Return ripgrep matches for ``pattern`` under ``root``.

    Args:
        pattern: regex (or literal if ``fixed``) to search for.
        root: workspace directory to search within.
        word: match on word boundaries (``--word-regexp``).
        fixed: treat ``pattern`` as a literal string (``--fixed-strings``).
        globs: optional ``--glob`` filters (e.g. ``"*.py"``).
        max_count: cap matches per file.
    """
    rg = _rg_binary()
    if rg is None:
        return _python_search(
            pattern, root, word=word, fixed=fixed, globs=globs, max_count=max_count
        )
    cmd = [rg, "--json"]
    if word:
        cmd.append("--word-regexp")
    if fixed:
        cmd.append("--fixed-strings")
    if max_count is not None:
        cmd += ["--max-count", str(max_count)]
    for g in globs or ():
        cmd += ["--glob", g]
    cmd += ["--", pattern, str(root)]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # rg exits 1 when there are no matches; >1 is a real error.
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"ripgrep failed ({proc.returncode}): {proc.stderr.strip()}")

    hits: list[SearchHit] = []
    for raw in proc.stdout.splitlines():
        if not raw:
            continue
        event = json.loads(raw)
        if event.get("type") != "match":
            continue
        data = event["data"]
        abs_path = Path(data["path"]["text"])
        rel = _relativize(abs_path, root)
        line_no = data["line_number"]
        text = data["lines"]["text"].rstrip("\n")
        # submatches give 0-based byte offsets; +1 for a 1-based column.
        subs = data.get("submatches") or [{"start": 0}]
        column = subs[0]["start"] + 1
        hits.append(SearchHit(location=Location(path=rel, line=line_no, column=column), text=text))
    return hits


def _relativize(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _python_search(
    pattern: str,
    root: Path,
    *,
    word: bool,
    fixed: bool,
    globs: Iterable[str] | None,
    max_count: int | None,
) -> list[SearchHit]:
    """Pure-Python fallback matching :func:`search`'s contract (no ``rg``)."""
    root = root.resolve()
    regex = re.escape(pattern) if fixed else pattern
    if word:
        regex = rf"\b(?:{regex})\b"
    try:
        compiled = re.compile(regex)
    except re.error as exc:  # mirror rg's "real error" path
        raise RuntimeError(f"invalid search pattern: {exc}") from exc

    glob_list = list(globs) if globs else ["*"]
    hits: list[SearchHit] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if not any(path.match(g) for g in glob_list):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        except (OSError, UnicodeDecodeError):
            continue  # skip binary / unreadable files, like rg does
        rel = str(path.relative_to(root))
        per_file = 0
        for line_no, line in enumerate(lines, start=1):
            match = compiled.search(line)
            if match is None:
                continue
            hits.append(
                SearchHit(
                    location=Location(path=rel, line=line_no, column=match.start() + 1),
                    text=line,
                )
            )
            per_file += 1
            if max_count is not None and per_file >= max_count:
                break
    return hits
