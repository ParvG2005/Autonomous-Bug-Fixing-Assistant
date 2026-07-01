"""Repo management endpoints for the UI control plane.

Add a repo by URL (fix-only), list, delete, and — via worker tasks that own all
GitHub I/O — connect a GitHub App install or trigger a discovery scan.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_queue, get_session
from app.db.repos import create_repo, delete_repo, list_repos, parse_repo_url
from app.models.entities import Repo
from app.workers.queue import JobQueue

router = APIRouter(prefix="/repos", tags=["repos"])


class AddRepoBody(BaseModel):
    clone_url: str


class RepoView(BaseModel):
    id: str
    full_name: str
    publish_capable: bool
    created_at: datetime


def _view(repo: Repo) -> RepoView:
    return RepoView(
        id=str(repo.id),
        full_name=repo.full_name,
        publish_capable=repo.installation_id is not None,
        created_at=repo.created_at,
    )


def _parse_id(repo_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(repo_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed repo id") from exc


@router.get("", response_model=list[RepoView])
async def get_repos(session: AsyncSession = Depends(get_session)) -> list[RepoView]:
    return [_view(r) for r in await list_repos(session)]


@router.post("", response_model=RepoView, status_code=status.HTTP_201_CREATED)
async def add_repo(body: AddRepoBody, session: AsyncSession = Depends(get_session)) -> RepoView:
    try:
        full_name, source_url = parse_repo_url(body.clone_url)
        repo = await create_repo(session, full_name, source_url=source_url)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return _view(repo)


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_repo(repo_id: str, session: AsyncSession = Depends(get_session)) -> None:
    try:
        await delete_repo(session, _parse_id(repo_id))
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()


async def _enqueue(queue: object | None, task: str, repo_id: str) -> None:
    if not isinstance(queue, JobQueue):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "worker queue not configured")
    await queue.enqueue_task(task, repo_id, dedup_key=f"{task}:{repo_id}")


@router.post("/{repo_id}/connect", status_code=status.HTTP_202_ACCEPTED)
async def connect(repo_id: str, queue: object | None = Depends(get_queue)) -> dict[str, str]:
    await _enqueue(queue, "connect_repo", repo_id)
    return {"status": "connecting", "repo_id": repo_id}


@router.post("/{repo_id}/scan", status_code=status.HTTP_202_ACCEPTED)
async def scan(repo_id: str, queue: object | None = Depends(get_queue)) -> dict[str, str]:
    await _enqueue(queue, "scan_repo", repo_id)
    return {"status": "scanning", "repo_id": repo_id}
