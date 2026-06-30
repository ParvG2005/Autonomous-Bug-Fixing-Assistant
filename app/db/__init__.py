"""Async database engine, session factory, and data-access services (Phase 6+).

Trusted plane. The engine is built from ``Settings.database_url`` (an async
SQLAlchemy URL — ``postgresql+psycopg://…`` in prod, ``sqlite+aiosqlite://…`` in
tests). Business logic lives in services (e.g. :mod:`app.db.jobs`), not in the
HTTP layer.
"""
