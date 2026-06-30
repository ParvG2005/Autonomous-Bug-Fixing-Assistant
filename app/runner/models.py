"""Value types produced by the test runner.

A run yields a :class:`TestRunResult`: aggregate pass/fail counts plus, for each
failing test, the exception message and the parsed stack-trace frames. Frames are
``{file, line, function}`` (DATA_MODEL.md / BUILD_PLAN.md Phase 2) and are
workspace-relative when the path falls inside the workspace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Framework(StrEnum):
    """Test frameworks the runner can detect and drive (one per language adapter).

    Phase 8 generalizes the runner beyond pytest: each member maps to a
    :class:`~app.runner.adapters.base.LanguageAdapter` in the registry.
    """

    PYTEST = "pytest"  # Python
    NODE_TEST = "node-test"  # JS/TS — node's built-in test runner
    GO_TEST = "go-test"  # Go — `go test`
    CARGO_TEST = "cargo-test"  # Rust — `cargo test`
    RSPEC = "rspec"  # Ruby — rspec / minitest via rake
    MAVEN = "maven"  # Java/Kotlin (JVM) — `mvn test`
    GRADLE = "gradle"  # Java/Kotlin (JVM) — `gradle test`
    DOTNET = "dotnet"  # C#/F#/.NET — `dotnet test`
    PHPUNIT = "phpunit"  # PHP — phpunit
    MIX_TEST = "mix-test"  # Elixir — `mix test`


class Outcome(StrEnum):
    """Overall result of a test run."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"  # collection / import errors, internal pytest errors
    NO_TESTS = "no_tests"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class TraceFrame:
    """One stack-trace frame: where execution was when it failed."""

    file: str
    line: int
    function: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line} in {self.function}"


@dataclass(frozen=True)
class TestFailure:
    """A single failing (or erroring) test.

    ``frames`` are ordered outermost→innermost as Python reports them, so the
    last frame is usually the most relevant fix site.
    """

    nodeid: str
    message: str
    frames: list[TraceFrame] = field(default_factory=list)

    @property
    def innermost_frame(self) -> TraceFrame | None:
        """The deepest frame — the likeliest place the bug lives."""
        return self.frames[-1] if self.frames else None


@dataclass
class TestRunResult:
    """Structured outcome of running a project's tests."""

    framework: Framework
    outcome: Outcome
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    failures: list[TestFailure] = field(default_factory=list)
    duration_s: float = 0.0
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        """True when the suite ran and nothing failed or errored."""
        return self.outcome == Outcome.PASSED
