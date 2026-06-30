"""ORM entities — repos, jobs, runs, artifacts, fixes, approvals, code chunks.

Mirrors docs/DATA_MODEL.md. Secrets are never stored here (invariant 1): the
GitHub installation token is minted at PR time and discarded, and untrusted issue
text lives in an ARTIFACT, not inline on the hot JOB row (``issue_body_ref``).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    JSONType,
    created_at_column,
    enum_column,
    fk_uuid,
    updated_at_column,
    uuid_pk,
)


class JobState(enum.StrEnum):
    """Job lifecycle (see DATA_MODEL.md §3). Terminal: done, failed."""

    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    DONE = "done"
    FAILED = "failed"


class JobTrigger(enum.StrEnum):
    WEBHOOK = "webhook"
    MANUAL = "manual"
    EVAL = "eval"


class RunPhase(enum.StrEnum):
    REPRODUCE = "reproduce"
    LOCALIZE = "localize"
    FIX = "fix"
    VERIFY = "verify"


class RunStatus(enum.StrEnum):
    OK = "ok"
    FAIL = "fail"
    ERROR = "error"


class ArtifactKind(enum.StrEnum):
    DIFF = "diff"
    TEST_OUTPUT = "test_output"
    STACKTRACE = "stacktrace"
    LOG = "log"
    REASONING = "reasoning"
    ISSUE_BODY = "issue_body"


class ArtifactStorage(enum.StrEnum):
    INLINE_SMALL = "inline_small"
    BLOB_REF = "blob_ref"


class ApprovalDecision(enum.StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class Repo(Base):
    """One installed repository; ``installation_id`` mints PR-time tokens."""

    __tablename__ = "repo"

    id: Mapped[uuid.UUID] = uuid_pk()
    gh_repo_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    installation_id: Mapped[int] = mapped_column(BigInteger)
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    jobs: Mapped[list[Job]] = relationship(back_populates="repo")


class Job(Base):
    """The unit of work — one issue to fix."""

    __tablename__ = "job"
    __table_args__ = (
        Index("ix_job_repo_state", "repo_id", "state"),
        # One live job per (repo, issue): blocks duplicate webhook deliveries.
        UniqueConstraint("repo_id", "gh_issue_number", "state", name="uq_job_repo_issue_state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID] = fk_uuid("repo.id")
    gh_issue_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trigger: Mapped[JobTrigger] = enum_column(JobTrigger, default=JobTrigger.WEBHOOK)
    issue_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_body_ref: Mapped[uuid.UUID | None] = mapped_column(nullable=True)  # ARTIFACT id
    state: Mapped[JobState] = enum_column(JobState, default=JobState.QUEUED)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    cost: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    repo: Mapped[Repo] = relationship(back_populates="jobs")
    runs: Mapped[list[Run]] = relationship(back_populates="job")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="job")


class Run(Base):
    """One attempt-phase of a job; links to its full Langfuse trace."""

    __tablename__ = "run"
    __table_args__ = (Index("ix_run_job_attempt", "job_id", "attempt"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = fk_uuid("job.id")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    phase: Mapped[RunPhase] = enum_column(RunPhase)
    status: Mapped[RunStatus] = enum_column(RunStatus)
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    started_at: Mapped[datetime] = created_at_column()
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)

    job: Mapped[Job] = relationship(back_populates="runs")


class Artifact(Base):
    """Append-only payload store; small inline, large by blob reference."""

    __tablename__ = "artifact"
    __table_args__ = (Index("ix_artifact_job_kind", "job_id", "kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = fk_uuid("job.id")
    run_id: Mapped[uuid.UUID | None] = fk_uuid("run.id", nullable=True)
    kind: Mapped[ArtifactKind] = enum_column(ArtifactKind)
    storage: Mapped[ArtifactStorage] = enum_column(
        ArtifactStorage, default=ArtifactStorage.INLINE_SMALL
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    blob_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()

    job: Mapped[Job] = relationship(back_populates="artifacts")


class Fix(Base):
    """The proposed patch; ``flags`` carries guardrail outcomes."""

    __tablename__ = "fix"

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = fk_uuid("job.id")
    diff_artifact_id: Mapped[uuid.UUID | None] = fk_uuid("artifact.id", nullable=True)
    reasoning_artifact_id: Mapped[uuid.UUID | None] = fk_uuid("artifact.id", nullable=True)
    diff_lines_added: Mapped[int] = mapped_column(Integer, default=0)
    diff_lines_removed: Mapped[int] = mapped_column(Integer, default=0)
    wrote_repro_test: Mapped[bool] = mapped_column(Boolean, default=False)
    flags: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    tests_pass: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_column()


class Approval(Base):
    """The human gate, persisted. Immutable; a reversal is a new row."""

    __tablename__ = "approval"
    __table_args__ = (Index("ix_approval_job", "job_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = fk_uuid("job.id")
    decision: Mapped[ApprovalDecision] = enum_column(ApprovalDecision)
    actor: Mapped[str] = mapped_column(String(255))
    actor_source: Mapped[str] = mapped_column(String(32), default="dashboard")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = created_at_column()


class CodeChunk(Base):
    """pgvector embeddings for fallback semantic retrieval.

    The ``embedding`` vector column is added by the Phase-1/RAG migration when
    pgvector is enabled; the table is defined here so the schema is complete.
    """

    __tablename__ = "code_chunk"
    __table_args__ = (Index("ix_code_chunk_repo", "repo_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID] = fk_uuid("repo.id")
    path: Mapped[str] = mapped_column(String(1024))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str | None] = mapped_column(String(255), nullable=True)
    indexed_at: Mapped[datetime] = created_at_column()
