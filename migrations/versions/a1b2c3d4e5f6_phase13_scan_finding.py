"""phase 13: scan + finding tables, job.finding_id

Revision ID: a1b2c3d4e5f6
Revises: 4c67766feb30
Create Date: 2026-06-30 16:00:00.000000

Adds the proactive-discovery data model (Phase 13). New ``JobTrigger`` values
(``discovery``, ``scrape``) need no migration — triggers are stored as VARCHAR
(``native_enum=False``), so widening the Python enum is schema-compatible.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "4c67766feb30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "scan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column(
            "trigger",
            sa.Enum("scheduled", "manual", "push", name="scantrigger", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum("running", "done", "failed", name="scanstate", native_enum=False),
            nullable=False,
        ),
        sa.Column("sources_run", _JSON, nullable=False),
        sa.Column("budget", _JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["repo_id"], ["repo.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("scan", schema=None) as batch_op:
        batch_op.create_index("ix_scan_repo", ["repo_id"], unique=False)

    op.create_table(
        "finding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "tests", "static", "runtime", "diff", "review",
                name="findingsource", native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("frames", _JSON, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "candidate", "reproduced", "promoted", "dismissed", "duplicate",
                name="findingstatus", native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repo.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo_id", "fingerprint", name="uq_finding_repo_fingerprint"),
    )
    with op.batch_alter_table("finding", schema=None) as batch_op:
        batch_op.create_index("ix_finding_scan", ["scan_id"], unique=False)

    # ``trigger`` is a VARCHAR-backed (non-native) enum; the new ``discovery`` /
    # ``scrape`` values widen the inferred column length, so the type is altered.
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.add_column(sa.Column("finding_id", sa.Uuid(), nullable=True))
        batch_op.alter_column(
            "trigger",
            existing_type=sa.String(length=7),
            type_=sa.Enum(
                "webhook", "manual", "eval", "discovery", "scrape",
                name="jobtrigger", native_enum=False,
            ),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.alter_column(
            "trigger",
            existing_type=sa.Enum(
                "webhook", "manual", "eval", "discovery", "scrape",
                name="jobtrigger", native_enum=False,
            ),
            type_=sa.String(length=7),
            existing_nullable=False,
        )
        batch_op.drop_column("finding_id")

    with op.batch_alter_table("finding", schema=None) as batch_op:
        batch_op.drop_index("ix_finding_scan")
    op.drop_table("finding")

    with op.batch_alter_table("scan", schema=None) as batch_op:
        batch_op.drop_index("ix_scan_repo")
    op.drop_table("scan")
