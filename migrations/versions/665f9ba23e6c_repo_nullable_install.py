"""repo nullable install

Revision ID: 665f9ba23e6c
Revises: a1b2c3d4e5f6
Create Date: 2026-07-01 00:39:33.661687

Relaxes ``repo.gh_repo_id`` and ``repo.installation_id`` to nullable so a
``Repo`` row can exist before the GitHub App is installed (UI control plane,
Phase 15 Task 1). Batch mode is required for SQLite compatibility.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "665f9ba23e6c"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("repo", schema=None) as batch:
        batch.alter_column("gh_repo_id", existing_type=sa.BigInteger(), nullable=True)
        batch.alter_column("installation_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("repo", schema=None) as batch:
        batch.alter_column("installation_id", existing_type=sa.BigInteger(), nullable=False)
        batch.alter_column("gh_repo_id", existing_type=sa.BigInteger(), nullable=False)
