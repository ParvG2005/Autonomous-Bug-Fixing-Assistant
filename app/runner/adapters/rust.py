"""Rust adapter — ``cargo test``.

Cargo's built-in test harness needs no extra deps. Failure output carries a
``test result: FAILED. N passed; M failed;`` summary and panic locations like
``thread 'tests::x' panicked at src/lib.rs:10:5``.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.runner.adapters.common import BaseRegexAdapter
from app.runner.models import Framework

RUST_IMAGE = "bugfix-sandbox-rust:latest"

_FRAME_RE = re.compile(r"(?P<file>[\w./@+-]+\.rs):(?P<line>\d+)(?::\d+)?")
_SUMMARY_RE = re.compile(r"test result:\s+\w+\.\s+(?P<passed>\d+) passed;\s+(?P<failed>\d+) failed")


class CargoTestAdapter(BaseRegexAdapter):
    framework = Framework.CARGO_TEST
    image = RUST_IMAGE
    commands = frozenset({"cargo"})
    frame_re = _FRAME_RE
    fail_marker = "panicked at"

    def detect(self, workspace: Path) -> bool:
        return (workspace / "Cargo.toml").is_file()

    def install_command(self, workspace: Path) -> list[str] | None:
        return ["cargo", "fetch"]

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        # `--no-fail-fast` so every failing test is reported, not just the first.
        if targets:
            return ["cargo", "test", "--no-fail-fast", "--", *targets]
        return ["cargo", "test", "--no-fail-fast"]

    def _count(self, combined: str) -> tuple[int, int, int]:
        passed = failed = 0
        for m in _SUMMARY_RE.finditer(combined):
            passed += int(m.group("passed"))
            failed += int(m.group("failed"))
        return (passed, failed, 0)
