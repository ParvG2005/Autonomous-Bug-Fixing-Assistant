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

# owner/repo, optionally followed by a GitHub web-UI path (/tree/<ref>,
# /blob/<ref>/..., /pull/<n>, /commit/<sha>) that a browser leaves on the URL.
# That suffix is not part of the repo identity — a branch/PR is a separate
# per-job `ref` input — so we match owner/repo and discard the rest.
_GH_URL_RE = re.compile(
    r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/(?:tree|blob|commit|pull|compare|releases)(?:/.*)?)?/?$"
)
_SHORT_RE = re.compile(r"^([\w.-]+)/([\w.-]+?)(?:\.git)?$")
# owner/name from any "host[:/]owner/name(.git)" remote (gitlab, bitbucket, self-hosted).
_ANY_REMOTE_RE = re.compile(r"[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def repo_clone_url(repo: Repo) -> str:
    """Where to clone this repo from. Falls back to the GitHub-cloud HTTPS URL."""
    return repo.source_url or f"https://github.com/{repo.full_name}.git"


def parse_repo_url(url: str) -> tuple[str, str | None]:
    """Classify a repo reference.

    Returns ``(full_name, source_url)``. ``source_url`` is ``None`` for
    GitHub-cloud inputs (clone URL is derived from ``full_name``); otherwise it
    is the literal git URL or local path to clone from.
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("empty repo url")

    # Local path: full_name is the basename; source is the literal path/url.
    # Must run before the "github.com" substring check below, since a local
    # path can legitimately contain that substring (e.g. a mirror directory
    # named "github.com-mirror").
    if url.startswith(("/", "./", "../", "~", "file://")):
        name = url.rstrip("/").split("/")[-1] or "repo"
        if name.endswith(".git"):
            name = name[:-4]
        return name, url

    # GitHub cloud: store only full_name, derive the URL later.
    if "github.com" in url:
        m = _GH_URL_RE.search(url)
        if m is None:
            raise ValueError(f"not a GitHub repo url: {url!r}")
        return f"{m.group(1)}/{m.group(2)}", None
    m = _SHORT_RE.match(url)
    if m is not None:
        return f"{m.group(1)}/{m.group(2)}", None

    # Any other git remote (gitlab, bitbucket, self-hosted, ssh).
    m = _ANY_REMOTE_RE.search(url)
    if m is None:
        raise ValueError(f"not a recognizable repo url or path: {url!r}")
    return f"{m.group(1)}/{m.group(2)}", url


async def _by_full_name(session: AsyncSession, full_name: str) -> Repo | None:
    return (
        await session.execute(select(Repo).where(Repo.full_name == full_name))
    ).scalar_one_or_none()


async def create_repo(session: AsyncSession, full_name: str, source_url: str | None = None) -> Repo:
    if await _by_full_name(session, full_name) is not None:
        raise ValueError(f"repo {full_name} already registered")
    repo = Repo(full_name=full_name, default_branch="main", source_url=source_url)
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
