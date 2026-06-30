"""Detection + parse for the extended language adapters (Phase 8 extension)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.runner.adapters import detect_adapter
from app.runner.adapters.dotnet import DotnetTestAdapter
from app.runner.adapters.elixir import MixTestAdapter
from app.runner.adapters.jvm import GradleAdapter, MavenAdapter
from app.runner.adapters.php import PhpUnitAdapter
from app.runner.adapters.ruby import RSpecAdapter
from app.runner.adapters.rust import CargoTestAdapter
from app.runner.models import Framework, Outcome
from app.sandbox.models import ExecResult


def _res(rc: int, out: str = "", err: str = "") -> ExecResult:
    return ExecResult(returncode=rc, stdout=out, stderr=err, duration_s=0.1, timed_out=False)


def test_detect_picks_the_right_adapter_by_manifest(tmp_path: Path) -> None:
    cases = {
        "Cargo.toml": Framework.CARGO_TEST,
        "pom.xml": Framework.MAVEN,
        "build.gradle": Framework.GRADLE,
        "mix.exs": Framework.MIX_TEST,
        "App.csproj": Framework.DOTNET,
        "composer.json": Framework.PHPUNIT,
    }
    for manifest, framework in cases.items():
        d = tmp_path / manifest.replace(".", "_")
        d.mkdir()
        (d / manifest).write_text("x", encoding="utf-8")
        adapter = detect_adapter(d)
        assert adapter is not None and adapter.framework is framework


def test_rust_summary_and_frames() -> None:
    out = (
        "running 2 tests\n"
        "thread 'tests::divides' panicked at src/lib.rs:14:9:\n"
        "assertion failed\n"
        "test result: FAILED. 1 passed; 1 failed; 0 ignored\n"
    )
    result = CargoTestAdapter().parse_result(_res(101, out), "/workspace")
    assert result.outcome is Outcome.FAILED
    assert (result.passed, result.failed) == (1, 1)
    assert any(f.file == "src/lib.rs" and f.line == 14 for f in result.failures[0].frames)


def test_maven_summary_counts() -> None:
    out = (
        "Tests run: 5, Failures: 1, Errors: 0, Skipped: 1\n"
        "at com.acme.CalcTest.d(CalcTest.java:10)\n"
    )
    result = MavenAdapter().parse_result(_res(1, out), "/workspace")
    assert result.outcome is Outcome.FAILED
    assert (result.passed, result.failed, result.skipped) == (3, 1, 1)
    frame = result.failures[0].frames[0]
    assert frame.file == "CalcTest.java" and frame.line == 10 and "CalcTest.d" in frame.function


def test_gradle_passes_on_zero_exit() -> None:
    result = GradleAdapter().parse_result(_res(0, "BUILD SUCCESSFUL\n"))
    assert result.outcome is Outcome.PASSED
    assert result.failures == []


def test_dotnet_summary_and_frames() -> None:
    out = (
        "Failed: 2, Passed: 7, Skipped: 0\n"
        "   at Acme.CalcTest.Divide() in /src/CalcTest.cs:line 22\n"
    )
    result = DotnetTestAdapter().parse_result(_res(1, out), "/src")
    assert (result.passed, result.failed) == (7, 2)
    assert any(f.file == "CalcTest.cs" and f.line == 22 for f in result.failures[0].frames)


def test_php_and_elixir_and_ruby_counts() -> None:
    php = PhpUnitAdapter().parse_result(
        _res(1, "Tests: 4, Assertions: 9, Failures: 1, Errors: 1.\n/src/CalcTest.php:30\n"), "/src"
    )
    assert (php.passed, php.failed) == (2, 2)

    ex = MixTestAdapter().parse_result(_res(1, "3 tests, 1 failure\ntest/calc_test.exs:8\n"), ".")
    assert (ex.passed, ex.failed) == (2, 1)

    rb = RSpecAdapter().parse_result(
        _res(1, "2 examples, 1 failure\n./lib/calc.rb:10:in `divide'\n"), "."
    )
    assert (rb.passed, rb.failed) == (1, 1)
    assert rb.failures[0].frames[0].function == "divide"


@pytest.mark.parametrize(
    "adapter",
    [CargoTestAdapter(), MavenAdapter(), DotnetTestAdapter(), PhpUnitAdapter(), MixTestAdapter()],
)
def test_build_command_includes_targets(adapter: object) -> None:
    cmd = adapter.build_command(["only_this"])  # type: ignore[attr-defined]
    assert "only_this" in " ".join(cmd)
