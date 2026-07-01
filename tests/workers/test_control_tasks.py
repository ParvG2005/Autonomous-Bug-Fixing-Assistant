import pytest
from sqlalchemy import select

from app.core.settings import get_settings
from app.db.repos import create_repo
from app.models.entities import Repo
from app.workers import control_tasks
from app.workers.queue import JobQueue


class _FakePool:
    def __init__(self):
        self.calls = []

    async def enqueue_job(self, task, *args, _job_id=None):
        self.calls.append((task, args, _job_id))
        return object()


@pytest.mark.asyncio
async def test_enqueue_task_passes_name_and_args():
    pool = _FakePool()
    q = JobQueue(pool)
    ok = await q.enqueue_task("scan_repo", "rid-1", dedup_key="scan:rid-1")
    assert ok is True
    assert pool.calls == [("scan_repo", ("rid-1",), "scan:rid-1")]


def test_control_tasks_are_async_callables():
    for name in ("connect_repo", "scan_repo", "publish_pr"):
        assert callable(getattr(control_tasks, name))


@pytest.mark.asyncio
async def test_connect_repo_sets_install(db, monkeypatch):
    async with db.session() as s:
        repo = await create_repo(s, "octo/demo")
        await s.commit()
        rid = str(repo.id)

    async def fake_resolve(settings, full_name):
        return (12345, 67890)  # (gh_repo_id, installation_id)

    monkeypatch.setattr(control_tasks, "_resolve_installation", fake_resolve)
    ctx = {"db": db, "settings": object()}
    result = await control_tasks.connect_repo(ctx, rid)
    assert result == "connected"
    async with db.session() as s:
        repo = (await s.execute(select(Repo).where(Repo.id == repo.id))).scalar_one()
        assert repo.installation_id == 67890
        assert repo.gh_repo_id == 12345


@pytest.mark.asyncio
async def test_connect_repo_unavailable_on_resolve_failure(db, monkeypatch):
    async with db.session() as s:
        repo = await create_repo(s, "octo/private")
        await s.commit()
        rid = str(repo.id)

    async def fake_resolve(settings, full_name):
        raise RuntimeError("app not installed")

    monkeypatch.setattr(control_tasks, "_resolve_installation", fake_resolve)
    ctx = {"db": db, "settings": object()}
    result = await control_tasks.connect_repo(ctx, rid)
    assert result == "unavailable"
    async with db.session() as s:
        repo = (await s.execute(select(Repo).where(Repo.id == repo.id))).scalar_one()
        assert repo.installation_id is None
        assert repo.gh_repo_id is None


@pytest.mark.asyncio
async def test_scan_repo_clones_and_scans(db, monkeypatch, tmp_path):
    async with db.session() as s:
        repo = await create_repo(s, "octo/demo")
        await s.commit()
        rid = str(repo.id)

    calls = {}

    def fake_clone(url, dest, **kw):
        calls["clone"] = (url, dest)
        return dest

    async def fake_run_scan(database, full_name, workspace, **kw):
        calls["scan"] = (full_name, kw.get("promote"))
        from app.discovery.service import ScanSummary

        return ScanSummary(
            scan_id="s1", sources_run=[], candidates=0, parked=0, duplicates=0, errors={}
        )

    monkeypatch.setattr(control_tasks, "clone_repo", fake_clone)
    monkeypatch.setattr(control_tasks, "run_scan", fake_run_scan)
    monkeypatch.setattr(control_tasks, "get_sandbox", lambda: object())

    ctx = {"db": db, "settings": get_settings()}
    result = await control_tasks.scan_repo(ctx, rid)
    assert result == "scanned"
    assert calls["clone"][0] == "https://github.com/octo/demo.git"
    assert calls["scan"] == ("octo/demo", False)


@pytest.mark.asyncio
async def test_scan_repo_clones_from_source_url(db, monkeypatch, tmp_path):
    async with db.session() as s:
        repo = await create_repo(s, "grp/proj", source_url="https://gitlab.com/grp/proj.git")
        await s.commit()
        rid = str(repo.id)

    calls = {}

    def fake_clone(url, dest, **kw):
        calls["clone"] = (url, dest)
        return dest

    async def fake_run_scan(database, full_name, workspace, **kw):
        calls["scan"] = (full_name, kw.get("promote"))
        from app.discovery.service import ScanSummary

        return ScanSummary(
            scan_id="s1", sources_run=[], candidates=0, parked=0, duplicates=0, errors={}
        )

    monkeypatch.setattr(control_tasks, "clone_repo", fake_clone)
    monkeypatch.setattr(control_tasks, "run_scan", fake_run_scan)
    monkeypatch.setattr(control_tasks, "get_sandbox", lambda: object())

    ctx = {"db": db, "settings": get_settings()}
    result = await control_tasks.scan_repo(ctx, rid)
    assert result == "scanned"
    assert calls["clone"][0] == "https://gitlab.com/grp/proj.git"


@pytest.mark.asyncio
async def test_publish_pr_opens_draft(db, monkeypatch):
    # Build a repo (with install), a job, an approved decision, and a BUNDLE artifact.
    import json

    from app.db.approvals import record_decision
    from app.db.jobs import ingest_manual_issue
    from app.db.repos import create_repo
    from app.models.entities import ApprovalDecision, Artifact, ArtifactKind

    async with db.session() as s:
        repo = await create_repo(s, "octo/demo")
        repo.installation_id = 999
        job = await ingest_manual_issue(s, repo_id=repo.id, body="x", title="t")
        await record_decision(s, job.id, ApprovalDecision.APPROVED, actor="me")
        s.add(
            Artifact(
                job_id=job.id,
                kind=ArtifactKind.BUNDLE,
                storage=__import__(
                    "app.models.entities", fromlist=["ArtifactStorage"]
                ).ArtifactStorage.INLINE_SMALL,
                content=json.dumps(
                    {
                        "job_id": str(job.id),
                        "repo": {"owner": "octo", "name": "demo", "installation_id": 0},
                        "base_branch": "main",
                        "head_branch": f"bugfix/{job.id}",
                        "title": "Fix: t",
                        "commit_message": "Fix: t",
                        "body": "b",
                        "changes": [{"path": "a.py", "content": "print(1)\n"}],
                        "reasoning_comment": "why",
                    }
                ),
                size_bytes=1,
                sha256="x",
            )
        )
        await s.commit()
        jid = str(job.id)

    class FakePR:
        number = 7
        url = "https://github.com/octo/demo/pull/7"

    def fake_publish(bundle, *, store, token_minter, **kw):
        assert bundle.repo.installation_id == 999  # live id, not the stored 0
        return FakePR()

    monkeypatch.setattr("app.workers.control_tasks.open_draft_pr_for_fix", fake_publish)
    monkeypatch.setattr(
        "app.workers.control_tasks.settings_token_minter",
        lambda s, *, now: lambda iid: "tok",
    )

    ctx = {"db": db, "settings": get_settings()}
    result = await control_tasks.publish_pr(ctx, jid)
    assert result == "https://github.com/octo/demo/pull/7"


@pytest.mark.asyncio
async def test_publish_pr_refuses_without_install(db):
    from app.db.jobs import ingest_manual_issue
    from app.db.repos import create_repo

    async with db.session() as s:
        repo = await create_repo(s, "octo/demo")  # installation_id None
        job = await ingest_manual_issue(s, repo_id=repo.id, body="x", title="t")
        await s.commit()
        jid = str(job.id)
    ctx = {"db": db, "settings": object()}
    result = await control_tasks.publish_pr(ctx, jid)
    assert result == "not_publish_capable"
