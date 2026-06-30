"""FixBundle helpers: collapse edits to final file content."""

from __future__ import annotations

from app.agent.models import FileEdit
from app.vcs.models import RepoRef, changes_from_edits


def test_repo_full_name() -> None:
    assert RepoRef(owner="a", name="b", installation_id=1).full_name == "a/b"


def test_changes_from_edits_coalesces_and_drops_noops() -> None:
    edits = [
        FileEdit(path="a.py", before="1\n", after="2\n"),
        FileEdit(path="a.py", before="2\n", after="3\n"),  # same file, later wins
        FileEdit(path="b.py", before="x\n", after="x\n"),  # net no-op, dropped
    ]
    changes = changes_from_edits(edits)
    assert len(changes) == 1
    assert changes[0].path == "a.py"
    assert changes[0].content == "3\n"
