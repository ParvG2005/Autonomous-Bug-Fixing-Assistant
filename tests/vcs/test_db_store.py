import pytest

from app.db.approvals import record_decision
from app.db.jobs import ingest_manual_issue
from app.db.repos import create_repo
from app.models.entities import ApprovalDecision
from app.vcs.approval import ApprovalError, Decision, assert_approved
from app.vcs.db_store import load_db_approval_store


@pytest.mark.asyncio
async def test_db_store_reflects_approval(db_session):
    repo = await create_repo(db_session, "octo/demo")
    job = await ingest_manual_issue(db_session, repo_id=repo.id, body="x", title="t")
    await record_decision(db_session, job.id, ApprovalDecision.APPROVED, actor="me")
    store = await load_db_approval_store(db_session, str(job.id))
    latest = store.latest(str(job.id))
    assert latest is not None and latest.decision is Decision.APPROVED
    assert_approved(store, str(job.id))  # does not raise


@pytest.mark.asyncio
async def test_db_store_unapproved_raises(db_session):
    repo = await create_repo(db_session, "octo/demo")
    job = await ingest_manual_issue(db_session, repo_id=repo.id, body="x", title="t")
    store = await load_db_approval_store(db_session, str(job.id))
    with pytest.raises(ApprovalError):
        assert_approved(store, str(job.id))
