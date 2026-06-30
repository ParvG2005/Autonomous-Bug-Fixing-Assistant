"""Eval datasets: the :class:`EvalCase` value object + the on-disk suite loader.

A case is the minimum the harness needs to run one fix: an id, the issue text the
agent receives, and a way to *materialize* a fresh workspace. The common case
ships its files inline (``files``); the SWE-bench path supplies a ``setup``
callable that clones a real repo (see :mod:`eval.swebench`) — the harness only
ever calls :meth:`EvalCase.materialize`, so both sources run through one path.

The shipped **custom** suite lives under ``eval/data/<suite>/<case>/`` as:

* ``meta.json`` — ``{"id"?, "language"?, "title"?, "expected_edit_paths"?}``
  (``id`` defaults to the directory name).
* ``issue.md`` — the raw issue text handed to :func:`~app.agent.solve.solve_issue`.
* ``workspace/`` — the buggy project files, copied verbatim into the run workspace.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

DATA_ROOT = Path(__file__).parent / "data"
CUSTOM_SUITE = "custom"


@dataclass(frozen=True)
class EvalCase:
    """One benchmark case: issue text + a way to build its starting workspace."""

    id: str
    issue_text: str
    files: Mapping[str, str] = field(default_factory=dict)
    language: str = "python"
    title: str | None = None
    expected_edit_paths: tuple[str, ...] = ()
    # Overrides the files-based materialize (e.g. SWE-bench clones a real repo).
    setup: Callable[[Path], None] | None = None

    def materialize(self, dest: Path) -> Path:
        """Write this case's starting files into ``dest`` (created if missing)."""
        dest.mkdir(parents=True, exist_ok=True)
        if self.setup is not None:
            self.setup(dest)
            return dest
        for rel, content in self.files.items():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return dest


def _load_case(case_dir: Path) -> EvalCase:
    meta_path = case_dir / "meta.json"
    issue_path = case_dir / "issue.md"
    if not meta_path.is_file() or not issue_path.is_file():
        raise ValueError(f"malformed eval case {case_dir.name}: need meta.json + issue.md")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    ws_dir = case_dir / "workspace"
    files: dict[str, str] = {}
    if ws_dir.is_dir():
        for path in sorted(ws_dir.rglob("*")):
            if path.is_file():
                files[path.relative_to(ws_dir).as_posix()] = path.read_text(encoding="utf-8")
    if not files:
        raise ValueError(f"eval case {case_dir.name} has no workspace/ files")

    return EvalCase(
        id=str(meta.get("id", case_dir.name)),
        issue_text=issue_path.read_text(encoding="utf-8"),
        files=files,
        language=str(meta.get("language", "python")),
        title=meta.get("title"),
        expected_edit_paths=tuple(meta.get("expected_edit_paths", ())),
    )


def load_suite(name: str = CUSTOM_SUITE, *, root: Path | None = None) -> list[EvalCase]:
    """Load every case under ``<root>/<name>/`` (sorted by directory name)."""
    suite_dir = (root or DATA_ROOT) / name
    if not suite_dir.is_dir():
        raise FileNotFoundError(f"no eval suite {name!r} at {suite_dir}")
    cases = [_load_case(d) for d in sorted(suite_dir.iterdir()) if d.is_dir()]
    if not cases:
        raise ValueError(f"eval suite {name!r} is empty")
    return cases
