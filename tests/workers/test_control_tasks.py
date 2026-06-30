import pytest
from sqlalchemy import select

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
