"""Elixir adapter — ``mix test``.

Mix is Elixir's build+test tool. Failures point at ``test/calc_test.exs:10`` (and
stack entries at ``lib/calc.ex:5``); the summary is ``N tests, M failures``.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.runner.adapters.common import BaseRegexAdapter
from app.runner.models import Framework

ELIXIR_IMAGE = "bugfix-sandbox-elixir:latest"

_FRAME_RE = re.compile(r"(?P<file>[\w./@+-]+\.exs?):(?P<line>\d+)")
_SUMMARY_RE = re.compile(r"(?P<tests>\d+) tests?,\s+(?P<failures>\d+) failures?")


class MixTestAdapter(BaseRegexAdapter):
    framework = Framework.MIX_TEST
    image = ELIXIR_IMAGE
    commands = frozenset({"mix"})
    frame_re = _FRAME_RE

    def detect(self, workspace: Path) -> bool:
        return (workspace / "mix.exs").is_file()

    def install_command(self, workspace: Path) -> list[str] | None:
        return ["mix", "deps.get"]

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        if targets:
            return ["mix", "test", *targets]
        return ["mix", "test"]

    def _count(self, combined: str) -> tuple[int, int, int]:
        m = _SUMMARY_RE.search(combined)
        if m is None:
            return (0, 0, 0)
        tests, failures = int(m.group("tests")), int(m.group("failures"))
        return (max(0, tests - failures), failures, 0)
