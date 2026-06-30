"""Alembic environment.

The database URL comes from application settings (``DATABASE_URL``), not
``alembic.ini`` — secrets stay in one place. Migrations run synchronously; the
async drivers used at runtime (psycopg / aiosqlite) are coerced to their sync
equivalents here so Alembic's blocking engine works.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.settings import get_settings
from app.models.base import Base

# Import entities for their side effect: registering tables on Base.metadata.
import app.models.entities  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url() -> str:
    settings = get_settings()
    url = settings.database_url or "sqlite:///./bugfix.db"
    # Coerce async drivers to sync for Alembic's blocking engine.
    url = url.replace("+aiosqlite", "")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
