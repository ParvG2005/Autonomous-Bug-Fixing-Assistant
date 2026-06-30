"""The job pipeline (Phase 7), fully offline.

Seeds a queued job in a SQLite DB, materializes the workspace from a local
fixture (no clone), drives the agent with a scripted fake client + a real
LocalSandbox, and asserts the job lands at the human gate with persisted runs,
a fix, a diff/reasoning artifact, and progress logs. Also covers the unresolved
and error paths, plus the queued-state guard (dedup / replay).
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.core.settings import Settings
from app.db.jobs import IssueRef, ingest_labeled_issue
from app.db.session import Database
from app.models.entities import (
    Artifact,
    ArtifactKind,
    Fix,
    Job,
    JobState,
    Run,
    RunPhase,
    RunStatus,
)
from app.sandbox import LocalSandbox
from app.workers.pipeline import RepoInfo, run_pipeline
from app.workers.progress import read_logs

_ISSUE = """\
divide by zero crashes

`divide(1, 0)` raises instead of returning 0.

Traceback (most recent call last):
  File "calc.py", line 5, in divide
    return a / b
ZeroDivisionError: division by zero

Repro test: test_calc.py::test_divide_by_zero
"""


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
            _Response([_Text("Plan: guard divide against a zero denominator.")], "end_turn"),
            _Response(
                [
                    _ToolUse(
                        "t1",
                        "edit_file",
                        {
                            "path": "calc.py",
                            "old_str": "def divide(a, b):\n    return a / b",
                            "new_str": (
                                "def divide(a, b):\n    if b == 0:\n        return 0\n"
                                "    return a / b"
                            ),
                        },
                    )
                ],
                "tool_use",
            ),
            _Response([_Text("Guarded divide() against a zero denominator.")], "end_turn"),
        ]
    )


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'pipe.db'}")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


async def _seed_job(db: Database, body: str = _ISSUE) -> str:
    async with db.session() as session:
        result = await ingest_labeled_issue(
            session,
            IssueRef(
                gh_repo_id=1,
                full_name="acme/widgets",
                installation_id=1,
                gh_issue_number=7,
                issue_title="divide by zero",
                issue_body=body,
            ),
        )
        return str(result.job.id)


def _copy_from(source: Path) -> Any:
    def prepare(repo: RepoInfo, dest: Path) -> Path:
        shutil.copytree(source, dest)
        return dest

    return prepare


def _settings(tmp_path: Path) -> Settings:
    return Settings(app_env="local", workspace_root=tmp_path / "ws", agent_model="claude-opus-4-8")


async def test_pipeline_runs_to_human_gate(
    db: Database, failing_project: Path, tmp_path: Path
) -> None:
    job_id = await _seed_job(db)
    client = _fix_script()

    final = await run_pipeline(
        db,
        job_id,
        create_message=client.create,
        settings=_settings(tmp_path),
        prepare_workspace=_copy_from(failing_project),
        sandbox=LocalSandbox(),
    )

    assert final is JobState.AWAITING_APPROVAL  # human gate — never auto-published

    async with db.session() as session:
        job = (await session.execute(select(Job))).scalar_one()
        assert job.state is JobState.AWAITING_APPROVAL
        assert job.cost.get("output_tokens", 0) > 0

        runs = {r.phase: r for r in (await session.execute(select(Run))).scalars().all()}
        assert runs[RunPhase.VERIFY].status is RunStatus.OK
        assert runs[RunPhase.FIX].status is RunStatus.OK

        fix = (await session.execute(select(Fix))).scalar_one()
        assert fix.tests_pass is True
        assert fix.diff_lines_added > 0

        logs = await read_logs(session, job.id)
        assert any("awaiting human approval" in (a.content or "") for a in logs)

        # The diff + reasoning were persisted as artifacts.
        kinds = {a.kind for a in (await session.execute(select(Artifact))).scalars().all()}
        assert ArtifactKind.DIFF in kinds and ArtifactKind.REASONING in kinds


async def test_pipeline_unresolved_fails(
    db: Database, failing_project: Path, tmp_path: Path
) -> None:
    job_id = await _seed_job(db)
    # The model proposes nothing — the failing test stays red.
    client = _ScriptedClient(
        [
            _Response([_Text("Plan: investigate.")], "end_turn"),
            _Response([_Text("I cannot determine a fix.")], "end_turn"),
        ]
    )

    final = await run_pipeline(
        db,
        job_id,
        create_message=client.create,
        settings=_settings(tmp_path),
        prepare_workspace=_copy_from(failing_project),
        sandbox=LocalSandbox(),
    )

    assert final is JobState.FAILED
    async with db.session() as session:
        job = (await session.execute(select(Job))).scalar_one()
        assert job.state is JobState.FAILED
        assert job.failure_reason


async def test_pipeline_clone_error_fails(db: Database, tmp_path: Path) -> None:
    job_id = await _seed_job(db)

    def boom(repo: RepoInfo, dest: Path) -> Path:
        raise RuntimeError("clone exploded")

    final = await run_pipeline(
        db,
        job_id,
        create_message=_fix_script().create,
        settings=_settings(tmp_path),
        prepare_workspace=boom,
        sandbox=LocalSandbox(),
    )

    assert final is JobState.FAILED
    async with db.session() as session:
        job = (await session.execute(select(Job))).scalar_one()
        assert "clone exploded" in (job.failure_reason or "")


async def test_pipeline_skips_a_non_queued_job(
    db: Database, failing_project: Path, tmp_path: Path
) -> None:
    job_id = await _seed_job(db)
    settings = _settings(tmp_path)
    prepare = _copy_from(failing_project)

    first = await run_pipeline(
        db,
        job_id,
        create_message=_fix_script().create,
        settings=settings,
        prepare_workspace=prepare,
        sandbox=LocalSandbox(),
    )
    assert first is JobState.AWAITING_APPROVAL

    # A replay / duplicate enqueue must not re-run the pipeline.
    called = False

    def guard(repo: RepoInfo, dest: Path) -> Path:
        nonlocal called
        called = True
        return dest

    second = await run_pipeline(
        db,
        job_id,
        create_message=_fix_script().create,
        settings=settings,
        prepare_workspace=guard,
        sandbox=LocalSandbox(),
    )
    assert second is JobState.AWAITING_APPROVAL  # reports current state, unchanged
    assert called is False  # workspace was never prepared again
