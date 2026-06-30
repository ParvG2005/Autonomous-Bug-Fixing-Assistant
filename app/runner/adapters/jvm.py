"""JVM adapters — Maven and Gradle (Java and Kotlin).

Both run JUnit-style suites and emit stack frames like
``at com.acme.CalcTest.divide(CalcTest.java:10)`` (or ``Calc.kt``). Maven prints a
``Tests run: N, Failures: F, Errors: E, Skipped: S`` summary; Gradle's exit code
is the reliable signal (its console summary is terser).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.runner.adapters.common import BaseRegexAdapter
from app.runner.models import Framework

JVM_IMAGE = "bugfix-sandbox-jvm:latest"

# `at com.acme.CalcTest.divide(CalcTest.java:10)` — capture method + file:line.
_FRAME_RE = re.compile(
    r"at\s+(?P<func>[\w.$]+)\((?P<file>[\w$./-]+\.(?:java|kt|scala|groovy)):(?P<line>\d+)\)"
)
_MAVEN_SUMMARY_RE = re.compile(
    r"Tests run:\s+(?P<run>\d+),\s+Failures:\s+(?P<fail>\d+),"
    r"\s+Errors:\s+(?P<err>\d+),\s+Skipped:\s+(?P<skip>\d+)"
)


class MavenAdapter(BaseRegexAdapter):
    framework = Framework.MAVEN
    image = JVM_IMAGE
    commands = frozenset({"mvn"})
    frame_re = _FRAME_RE
    fail_marker = "FAILED"

    def detect(self, workspace: Path) -> bool:
        return (workspace / "pom.xml").is_file()

    def install_command(self, workspace: Path) -> list[str] | None:
        # Offline-resolve deps; the build also resolves but this primes the cache.
        return ["mvn", "-q", "-B", "dependency:resolve"]

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        if targets:
            return ["mvn", "-q", "-B", "test", f"-Dtest={','.join(targets)}"]
        return ["mvn", "-q", "-B", "test"]

    def _count(self, combined: str) -> tuple[int, int, int]:
        passed = failed = skipped = 0
        for m in _MAVEN_SUMMARY_RE.finditer(combined):
            run, fail, err, skip = (int(m.group(g)) for g in ("run", "fail", "err", "skip"))
            failed += fail + err
            skipped += skip
            passed += max(0, run - fail - err - skip)
        return (passed, failed, skipped)


class GradleAdapter(BaseRegexAdapter):
    framework = Framework.GRADLE
    image = JVM_IMAGE
    commands = frozenset({"gradle"})
    frame_re = _FRAME_RE
    fail_marker = "FAILED"

    def detect(self, workspace: Path) -> bool:
        return any(
            (workspace / f).is_file()
            for f in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")
        )

    def install_command(self, workspace: Path) -> list[str] | None:
        return None  # gradle resolves on the test task

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        cmd = ["gradle", "test", "--console=plain"]
        for t in targets or []:
            cmd += ["--tests", t]
        return cmd
