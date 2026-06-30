"""Phase 13 acceptance — discovery feeds the existing pipeline, fully offline.

A real detector (the existing-test signal) scans a repo with a latent bug (a
failing test, no filed issue), triage promotes the candidate into a synthetic
discovery job, and the **unchanged** worker pipeline (scripted fix client +
LocalSandbox) reproduces → fixes → verifies green → parks it at the human gate.
A second scan re-checks the same repo and, thanks to fingerprint dedup, refiles
nothing.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.settings import Settings
from app.db.discovery import create_scan, finish_scan, known_fingerprints, promote_candidate
from app.db.session import Database
from app.discovery.scan import scan_repo
from app.discovery.sources.tests import ExistingTestsDetector
from app.discovery.triage import triage
from app.models.entities import (
    Finding,
    FindingStatus,
    Job,
    JobState,
    JobTrigger,
    Repo,
    Scan,
    ScanState,
)
from app.sandbox import LocalSandbox
from app.workers.pipeline import RepoInfo, run_pipeline


# --- a scripted model client that fixes the factorial off-by-one ---------
@dataclass
class _Text:
    text: str
    type: str = "text"


@dataclass
class _ToolUse:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class _Usage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class _Response:
    content: list[Any]
    stop_reason: str
    usage: _Usage = field(default_factory=_Usage)


class _ScriptedClient:
    def __init__(self, responses: list[_Response]) -> None:
        self._responses = list(responses)

    def create(self, **kwargs: Any) -> _Response:
        return self._responses.pop(0)


def _fix_script() -> _ScriptedClient:
    return _ScriptedClient(
        [
            _Response([_Text("Plan: include n in the factorial product range.")], "end_turn"),
            _Response(
                [
                    _ToolUse(
                        "t1",
                        "edit_file",
                        {
                            "path": "mathutil.py",
                            "old_str": "    for i in range(1, n):",
                            "new_str": "    for i in range(1, n + 1):",
                        },
                    )
                ],
                "tool_use",
            ),
            _Response([_Text("Fixed the off-by-one in factorial().")], "end_turn"),
        ]
    )


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'disc.db'}")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


def _copy_from(source: Path) -> Any:
    def prepare(repo: RepoInfo, dest: Path) -> Path:
        shutil.copytree(source, dest)
        return dest

    return prepare


def _settings(tmp_path: Path) -> Settings:
    return Settings(app_env="local", workspace_root=tmp_path / "ws", agent_model="claude-opus-4-8")


async def _make_repo(db: Database) -> str:
    async with db.session() as session:
        repo = Repo(
            gh_repo_id=1, full_name="acme/widgets", installation_id=1, default_branch="main"
        )
        session.add(repo)
        await session.flush()
        return str(repo.id)


async def _scan_and_promote(db: Database, repo_id: str, workspace: Path) -> str | None:
    """Run a scan, triage, and promote the top candidate. Returns the job id (or None)."""
    scan_out = scan_repo(workspace, [ExistingTestsDetector()], sandbox=LocalSandbox())
    assert scan_out.candidates, "the existing-test detector should flag the failing test"

    import uuid

    async with db.session() as session:
        scan = await create_scan(session, uuid.UUID(repo_id))
        known = await known_fingerprints(session, uuid.UUID(repo_id))
        verdict = triage(scan_out.candidates, known_fingerprints=known, max_jobs=5)
        job_id: str | None = None
        for cand in verdict.promote:
            _, job = await promote_candidate(session, scan, cand)
            job_id = job_id or str(job.id)
        await finish_scan(session, scan, sources_run=scan_out.sources_run, state=ScanState.DONE)
        return job_id


async def test_discovery_promotes_repros_and_parks_at_human_gate(
    db: Database, agent_fixable: Path, tmp_path: Path
) -> None:
    repo_id = await _make_repo(db)

    job_id = await _scan_and_promote(db, repo_id, agent_fixable)
    assert job_id is not None

    # The promoted job is a discovery job referencing its finding.
    async with db.session() as session:
        job = (await session.execute(select(Job).where(Job.id.is_not(None)))).scalar_one()
        assert job.trigger is JobTrigger.DISCOVERY
        assert job.finding_id is not None
        assert job.gh_issue_number is None

    # The unchanged pipeline reproduces → fixes → verifies → human gate.
    final = await run_pipeline(
        db,
        job_id,
        create_message=_fix_script().create,
        settings=_settings(tmp_path),
        prepare_workspace=_copy_from(agent_fixable),
        sandbox=LocalSandbox(),
    )
    assert final is JobState.AWAITING_APPROVAL  # never auto-published (C1)

    async with db.session() as session:
        finding = (await session.execute(select(Finding))).scalar_one()
        assert finding.status is FindingStatus.PROMOTED
        assert finding.job_id is not None


async def test_rescan_does_not_refile_a_known_finding(db: Database, agent_fixable: Path) -> None:
    repo_id = await _make_repo(db)

    first = await _scan_and_promote(db, repo_id, agent_fixable)
    assert first is not None

    # A second scan sees the same failing test, but its fingerprint is known.
    second = await _scan_and_promote(db, repo_id, agent_fixable)
    assert second is None  # nothing promoted

    async with db.session() as session:
        jobs = (await session.execute(select(func.count()).select_from(Job))).scalar_one()
        findings = (await session.execute(select(func.count()).select_from(Finding))).scalar_one()
        scans = (await session.execute(select(func.count()).select_from(Scan))).scalar_one()
    assert jobs == 1  # only the first scan filed a job
    assert findings == 1  # the dedup baseline blocked a refile
    assert scans == 2  # both scans recorded
