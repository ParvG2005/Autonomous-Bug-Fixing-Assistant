"""Repo registration service for the UI control plane.

A repo can be added by URL with no GitHub App install (``installation_id`` NULL,
"fix-only"); ``app.workers.control_tasks.connect_repo`` upgrades it later. The
fix pipeline clones from ``full_name`` so no install is required to fix.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Job, Repo
from app.workers.state import LIVE_STATES

_URL_RE = re.compile(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
_SHORT_RE = re.compile(r"^([\w.-]+)/([\w.-]+?)(?:\.git)?$")


def parse_repo_url(url: str) -> str:
    """Return ``owner/name`` from a GitHub URL or shorthand; raise on anything else."""
    url = (url or "").strip()
    if not url:
        raise ValueError("empty repo url")
    m = _URL_RE.search(url) or (_SHORT_RE.match(url) if "github.com" not in url else None)
    if m is None:
        raise ValueError(f"not a GitHub repo url: {url!r}")
    return f"{m.group(1)}/{m.group(2)}"


async def _by_full_name(session: AsyncSession, full_name: str) -> Repo | None:
    return (
        await session.execute(select(Repo).where(Repo.full_name == full_name))
    ).scalar_one_or_none()


async def create_repo(session: AsyncSession, full_name: str) -> Repo:
    if await _by_full_name(session, full_name) is not None:
        raise ValueError(f"repo {full_name} already registered")
    repo = Repo(full_name=full_name, default_branch="main")
    session.add(repo)
    await session.flush()
    return repo


async def list_repos(session: AsyncSession) -> list[Repo]:
    rows = await session.execute(select(Repo).order_by(Repo.created_at.desc()))
    return list(rows.scalars().all())


async def delete_repo(session: AsyncSession, repo_id: uuid.UUID) -> None:
    live = (
        await session.execute(
            select(Job.id).where(Job.repo_id == repo_id, Job.state.in_(LIVE_STATES)).limit(1)
        )
    ).first()
    if live is not None:
        raise ValueError("repo has a live job; cannot delete")
    repo = (await session.execute(select(Repo).where(Repo.id == repo_id))).scalar_one_or_none()
    if repo is not None:
        await session.delete(repo)
        await session.flush()
