"""PHP adapter — PHPUnit.

Runs the project's PHPUnit (``vendor/bin/phpunit`` when Composer-installed, else a
global ``phpunit``). Stack frames read ``/src/Calc.php:10`` and the summary is
``Tests: N, Assertions: A, Failures: F`` (``Errors`` may also appear).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.runner.adapters.common import BaseRegexAdapter, has_file_with_suffix
from app.runner.models import Framework

PHP_IMAGE = "bugfix-sandbox-php:latest"

_FRAME_RE = re.compile(r"(?P<file>[\w./@+-]+\.php):(?P<line>\d+)")
_SUMMARY_RE = re.compile(r"Tests:\s+(?P<tests>\d+).*?Failures:\s+(?P<failures>\d+)", re.DOTALL)
_ERRORS_RE = re.compile(r"Errors:\s+(?P<errors>\d+)")


class PhpUnitAdapter(BaseRegexAdapter):
    framework = Framework.PHPUNIT
    image = PHP_IMAGE
    commands = frozenset({"phpunit", "php", "composer"})
    frame_re = _FRAME_RE

    def detect(self, workspace: Path) -> bool:
        if any(
            (workspace / f).is_file() for f in ("phpunit.xml", "phpunit.xml.dist", "composer.json")
        ):
            return True
        return has_file_with_suffix(workspace, ("Test.php",))

    def install_command(self, workspace: Path) -> list[str] | None:
        return ["composer", "install"] if (workspace / "composer.json").is_file() else None

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        if targets:
            return ["phpunit", *targets]
        return ["phpunit"]

    def _count(self, combined: str) -> tuple[int, int, int]:
        m = _SUMMARY_RE.search(combined)
        if m is None:
            return (0, 0, 0)
        tests, failures = int(m.group("tests")), int(m.group("failures"))
        err_m = _ERRORS_RE.search(combined)
        failed = failures + (int(err_m.group("errors")) if err_m else 0)
        return (max(0, tests - failed), failed, 0)
