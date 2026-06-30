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
