"""job ref and pr_number

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-01 00:00:01.000000

Adds ``job.ref`` (arbitrary branch/tag/sha to check out) and ``job.pr_number``
(GitHub PR head to debug). Both NULL for webhook / legacy jobs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job", schema=None) as batch:
        batch.add_column(sa.Column("ref", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("pr_number", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("job", schema=None) as batch:
        batch.drop_column("pr_number")
        batch.drop_column("ref")
