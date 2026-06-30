"""Ruby adapter — RSpec.

Drives ``rspec`` (the dominant Ruby test framework). Backtraces look like
``./lib/calc.rb:10:in 'Calc.divide'`` and the summary is ``N examples, M failures``.
Bundler deps are installed first when a ``Gemfile`` is present.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.runner.adapters.common import BaseRegexAdapter, has_file_with_suffix
from app.runner.models import Framework

RUBY_IMAGE = "bugfix-sandbox-ruby:latest"

_FRAME_RE = re.compile(
    r"(?P<file>[\w./@+-]+\.rb):(?P<line>\d+)(?::in [`'](?P<func>[^'\"]+)['\"])?"
)
_SUMMARY_RE = re.compile(r"(?P<examples>\d+) examples?,\s+(?P<failures>\d+) failures?")


class RSpecAdapter(BaseRegexAdapter):
    framework = Framework.RSPEC
    image = RUBY_IMAGE
    commands = frozenset({"rspec", "bundle", "ruby", "rake"})
    frame_re = _FRAME_RE

    def detect(self, workspace: Path) -> bool:
        if (workspace / ".rspec").is_file() or (workspace / "spec").is_dir():
            return True
        return has_file_with_suffix(workspace, ("_spec.rb",))

    def install_command(self, workspace: Path) -> list[str] | None:
        return ["bundle", "install"] if (workspace / "Gemfile").is_file() else None

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        if targets:
            return ["rspec", *targets]
        return ["rspec"]

    def _count(self, combined: str) -> tuple[int, int, int]:
        m = _SUMMARY_RE.search(combined)
        if m is None:
            return (0, 0, 0)
        examples, failures = int(m.group("examples")), int(m.group("failures"))
        return (max(0, examples - failures), failures, 0)
