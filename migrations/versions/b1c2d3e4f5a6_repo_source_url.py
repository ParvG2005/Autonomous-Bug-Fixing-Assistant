"""repo source_url

Revision ID: b1c2d3e4f5a6
Revises: 665f9ba23e6c
Create Date: 2026-07-01 00:00:00.000000

Adds ``repo.source_url`` so a repo can be cloned from any git URL or local path,
not just ``https://github.com/{full_name}.git``. NULL preserves legacy behavior.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "665f9ba23e6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("repo", schema=None) as batch:
        batch.add_column(sa.Column("source_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("repo", schema=None) as batch:
        batch.drop_column("source_url")
