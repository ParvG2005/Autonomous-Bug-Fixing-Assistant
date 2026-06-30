import uuid

import pytest
from sqlalchemy import select

from app.db.jobs import ingest_manual_issue
from app.db.repos import create_repo
from app.models.entities import Artifact, ArtifactKind, JobState, JobTrigger


@pytest.mark.asyncio
async def test_manual_ingest_stores_body_and_queues(db_session):
    repo = await create_repo(db_session, "octo/demo")
    job = await ingest_manual_issue(
        db_session, repo_id=repo.id, body="boom\nTraceback ...", title="crash on save"
    )
    assert job.trigger == JobTrigger.MANUAL
    assert job.gh_issue_number is None
    assert job.state == JobState.QUEUED
    assert job.issue_title == "crash on save"
    art = (
        await db_session.execute(select(Artifact).where(Artifact.id == job.issue_body_ref))
    ).scalar_one()
    assert art.kind == ArtifactKind.ISSUE_BODY
    assert art.content == "boom\nTraceback ..."


@pytest.mark.asyncio
async def test_manual_ingest_unknown_repo(db_session):
    with pytest.raises(ValueError):
        await ingest_manual_issue(db_session, repo_id=uuid.uuid4(), body="x", title=None)
