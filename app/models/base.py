"""SQLAlchemy declarative base and portable column helpers (Phase 6).

The logical model in docs/DATA_MODEL.md targets Postgres, but the unit suite runs
against SQLite (no server needed). To let one set of models serve both, we avoid
Postgres-only constructs at the type level:

- ``Uuid`` maps to native ``uuid`` on Postgres and ``CHAR(32)`` on SQLite.
- ``JSONB`` is used on Postgres and plain ``JSON`` elsewhere via a variant.
- Enums are stored as ``VARCHAR`` (``native_enum=False``) so no Postgres enum
  type and no extra migration step is needed; the Python enum still validates.

Timestamps are timezone-aware with a server-side ``now()`` default.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSON on SQLite, JSONB on Postgres — same Python dict interface either way.
JSONType = JSON().with_variant(JSONB, "postgresql")


def enum_column(py_enum: type[enum.Enum], **kwargs: Any) -> Mapped[Any]:
    """A non-native (VARCHAR-backed) enum column storing the member *values*."""
    return mapped_column(
        Enum(py_enum, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        **kwargs,
    )


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def uuid_pk() -> Mapped[uuid.UUID]:
    """A UUID primary key with a client-side default (portable across dialects)."""
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def fk_uuid(target: str, *, nullable: bool = False, index: bool = False) -> Mapped[Any]:
    """A UUID foreign-key column referencing ``target`` (e.g. ``"job.id"``)."""
    from sqlalchemy import ForeignKey

    return mapped_column(
        Uuid, ForeignKey(target, ondelete="CASCADE"), nullable=nullable, index=index
    )


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_column() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
