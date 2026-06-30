import pytest

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
