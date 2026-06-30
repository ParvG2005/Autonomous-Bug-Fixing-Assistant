"""Shared fixtures: a tiny on-disk Python project to index and query."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database


@pytest.fixture
async def db_session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    """A fresh async SQLite-backed session, schema created via ``Base.metadata``."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.create_all()
    try:
        async with database.sessionmaker() as session:
            yield session
    finally:
        await database.dispose()


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    """A fresh ``Database`` (SQLite-backed) whose ``.session()`` is usable directly."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'control.db'}")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


_SAMPLE = '''\
"""Sample module for repo-brain tests."""


def greet(name):
    return f"hello {name}"


class Greeter:
    def __init__(self, prefix):
        self.prefix = prefix

    def greet(self, name):
        return greet(f"{self.prefix} {name}")


def main():
    g = Greeter("hi")
    print(g.greet("world"))
'''

_OTHER = """\
from sample import greet


def shout(name):
    return greet(name).upper()
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A minimal two-file Python workspace."""
    (tmp_path / "sample.py").write_text(_SAMPLE, encoding="utf-8")
    (tmp_path / "other.py").write_text(_OTHER, encoding="utf-8")
    (tmp_path / "README.md").write_text("# sample\n", encoding="utf-8")
    return tmp_path


# A known-failing pytest project for the Phase 2 runner: one failure that crosses
# two frames (test -> divide), one plain assertion failure, and one passing test.
_CALC = '''\
"""Tiny module under test."""


def divide(a, b):
    return a / b


def add(a, b):
    return a + b
'''

_TEST_CALC = """\
from calc import add, divide


def test_divide_by_zero():
    assert divide(1, 0) == 0


def test_add_ok():
    assert add(2, 3) == 5


def test_add_wrong():
    assert add(2, 2) == 5
"""


@pytest.fixture
def failing_project(tmp_path: Path) -> Path:
    """A pytest project with 1 passing and 2 failing tests."""
    (tmp_path / "calc.py").write_text(_CALC, encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(_TEST_CALC, encoding="utf-8")
    return tmp_path


# A project with a single, genuinely fixable bug for the Phase 3 agent loop:
# factorial iterates range(1, n) instead of range(1, n + 1), so it is off by the
# final factor. The one fix turns the whole (one-test) suite green.
_MATHUTIL = '''\
"""Arithmetic helpers under test."""


def factorial(n):
    result = 1
    for i in range(1, n):
        result *= i
    return result
'''

_TEST_MATHUTIL = """\
from mathutil import factorial


def test_factorial():
    assert factorial(1) == 1
    assert factorial(5) == 120
"""


@pytest.fixture
def agent_fixable(tmp_path: Path) -> Path:
    """A pytest project with one failing test fixable by a one-line source change."""
    (tmp_path / "mathutil.py").write_text(_MATHUTIL, encoding="utf-8")
    (tmp_path / "test_mathutil.py").write_text(_TEST_MATHUTIL, encoding="utf-8")
    return tmp_path


# A source-only project (NO test file) for the Phase 4 milestone: the agent must
# write a reproduction test for the reported bug before fixing it. ``titleize``
# upper-cases instead of title-casing.
_STRINGUTIL = '''\
"""String helpers."""


def titleize(text):
    return text.upper()
'''


@pytest.fixture
def source_only_bug(tmp_path: Path) -> Path:
    """A buggy module with no tests — Phase 4 must author a reproduction test."""
    (tmp_path / "stringutil.py").write_text(_STRINGUTIL, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    return tmp_path
