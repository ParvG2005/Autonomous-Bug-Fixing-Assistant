"""bugfix-pr CLI: record decisions, gate the `open` command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from app.vcs.cli import app

runner = CliRunner()


def _store(tmp_path: Path) -> list[str]:
    return ["--store", str(tmp_path / "approvals.jsonl")]


def test_approve_then_status(tmp_path: Path) -> None:
    s = _store(tmp_path)
    r = runner.invoke(app, ["approve", "job-1", "--actor", "alice", *s])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["status", "job-1", *s])
    assert r.exit_code == 0
    assert "approved" in r.output and "alice" in r.output


def test_status_unknown_job_exits_nonzero(tmp_path: Path) -> None:
    r = runner.invoke(app, ["status", "nope", *_store(tmp_path)])
    assert r.exit_code == 1


def test_open_without_confirm_refuses(tmp_path: Path) -> None:
    bundle = tmp_path / "fix.json"
    bundle.write_text(
        json.dumps(
            {
                "job_id": "job-1",
                "repo": {"owner": "acme", "name": "w", "installation_id": 1},
                "base_branch": "main",
                "head_branch": "fix/job-1",
                "title": "t",
                "commit_message": "m",
                "changes": [{"path": "a.py", "content": "x=1\n"}],
            }
        )
    )
    s = _store(tmp_path)
    runner.invoke(app, ["approve", "job-1", "--actor", "alice", *s])
    r = runner.invoke(app, ["open", "job-1", "--bundle", str(bundle), *s])
    assert r.exit_code == 2
    assert "--confirm" in r.output


def test_open_confirm_but_unapproved_is_refused(tmp_path: Path) -> None:
    bundle = tmp_path / "fix.json"
    bundle.write_text(
        json.dumps(
            {
                "job_id": "job-7",
                "repo": {"owner": "acme", "name": "w", "installation_id": 1},
                "base_branch": "main",
                "head_branch": "fix/job-7",
                "title": "t",
                "commit_message": "m",
                "changes": [{"path": "a.py", "content": "x=1\n"}],
            }
        )
    )
    # No approval recorded → publish aborts before minting a token.
    r = runner.invoke(
        app, ["open", "job-7", "--bundle", str(bundle), "--confirm", *_store(tmp_path)]
    )
    assert r.exit_code == 1
    assert "refused" in r.output
