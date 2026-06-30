"""Shared fixtures: a tiny on-disk Python project to index and query."""

from __future__ import annotations

from pathlib import Path

import pytest

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
