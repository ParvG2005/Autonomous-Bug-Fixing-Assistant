"""Job ingestion service — the webhook's only write path.

:func:`ingest_labeled_issue` is idempotent: a repeated ``autofix`` label delivery
for the same open issue returns the existing queued job rather than creating a
duplicate. Untrusted issue text is stored as an ARTIFACT (``issue_body``) and the
job references it (``issue_body_ref``); it is never inlined on the JOB row.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Artifact,
    ArtifactKind,
    ArtifactStorage,
    Job,
    JobState,
    JobTrigger,
    Repo,
)

# A queued/running/awaiting job is "live": a new label delivery must not re-enqueue.
_LIVE_STATES = (JobState.QUEUED, JobState.RUNNING, JobState.AWAITING_APPROVAL)

_DEFAULT_BUDGET = {"max_iterations": 20, "max_tokens": 400_000, "deadline_s": 600.0}


@dataclass(frozen=True)
class IssueRef:
    """The fields the ingestion path needs from an ``issues.labeled`` event."""

    gh_repo_id: int
    full_name: str
    installation_id: int
    gh_issue_number: int
    issue_title: str
    issue_body: str
    default_branch: str = "main"
    language: str | None = None


@dataclass(frozen=True)
class IngestResult:
    job: Job
    created: bool  # False when an existing live job was returned (idempotent hit)


async def _upsert_repo(session: AsyncSession, ref: IssueRef) -> Repo:
    repo = (
        await session.execute(select(Repo).where(Repo.gh_repo_id == ref.gh_repo_id))
    ).scalar_one_or_none()
    if repo is None:
        repo = Repo(
            gh_repo_id=ref.gh_repo_id,
            full_name=ref.full_name,
            installation_id=ref.installation_id,
            default_branch=ref.default_branch,
            language=ref.language,
        )
        session.add(repo)
        await session.flush()
    else:
        # Keep installation/branch current; an install can be re-keyed over time.
        repo.full_name = ref.full_name
        repo.installation_id = ref.installation_id
        repo.default_branch = ref.default_branch
    return repo


async def _existing_live_job(
    session: AsyncSession, repo_id: object, issue_number: int
) -> Job | None:
    return (
        (
            await session.execute(
                select(Job).where(
                    Job.repo_id == repo_id,
                    Job.gh_issue_number == issue_number,
                    Job.state.in_(_LIVE_STATES),
                )
            )
        )
        .scalars()
        .first()
    )


async def ingest_labeled_issue(
    session: AsyncSession,
    ref: IssueRef,
    *,
    trigger: JobTrigger = JobTrigger.WEBHOOK,
) -> IngestResult:
    """Create (or return) a queued job for a labeled issue. Idempotent per live job.

    ``trigger`` records provenance — the webhook passes ``webhook`` (default), the
    Phase 14 dev bootstrap passes ``scrape``. The ingest path is otherwise
    identical, so scraped issues flow through the same queue → worker → human gate.
    """
    repo = await _upsert_repo(session, ref)

    existing = await _existing_live_job(session, repo.id, ref.gh_issue_number)
    if existing is not None:
        return IngestResult(job=existing, created=False)

    body = ref.issue_body or ""
    body_bytes = body.encode("utf-8")
    artifact = Artifact(
        job_id=None,  # set after the job exists; artifact is created alongside below
        kind=ArtifactKind.ISSUE_BODY,
        storage=ArtifactStorage.INLINE_SMALL,
        content=body,
        size_bytes=len(body_bytes),
        sha256=hashlib.sha256(body_bytes).hexdigest(),
    )

    job = Job(
        repo_id=repo.id,
        gh_issue_number=ref.gh_issue_number,
        trigger=trigger,
        issue_title=ref.issue_title,
        state=JobState.QUEUED,
        budget=dict(_DEFAULT_BUDGET),
        cost={},
    )
    session.add(job)
    await session.flush()  # assign job.id

    artifact.job_id = job.id
    session.add(artifact)
    await session.flush()

    job.issue_body_ref = artifact.id
    await session.flush()

    return IngestResult(job=job, created=True)
