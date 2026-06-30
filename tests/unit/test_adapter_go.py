"""Parsing captured `go test ./... -v` output."""

from __future__ import annotations

from app.runner.adapters.golang import GoTestAdapter
from app.runner.models import Framework, Outcome
from app.sandbox.models import ExecResult

# `go test -v`: one pass, one failure with an inline t.Errorf log.
_GO_FAIL = """\
=== RUN   TestAdd
--- PASS: TestAdd (0.00s)
=== RUN   TestDivide
    calc_test.go:12: Divide(1, 0) = +Inf; want error
--- FAIL: TestDivide (0.00s)
FAIL
exit status 1
FAIL\texample/calc\t0.003s
"""

_GO_PASS = """\
=== RUN   TestAdd
--- PASS: TestAdd (0.00s)
PASS
ok\texample/calc\t0.002s
"""

_GO_NO_TESTS = """\
?\texample/calc\t[no test files]
"""

_GO_COMPILE_ERR = """\
# example/calc
./calc.go:5:2: undefined: foo
"""

_GO_PANIC = """\
=== RUN   TestDivide
--- FAIL: TestDivide (0.00s)
panic: runtime error: integer divide by zero

goroutine 19 [running]:
example/calc.Divide(...)
\t/workspace/calc.go:8
testing.tRunner(0xc0001234)
\t/usr/local/go/src/testing/testing.go:1689 +0x21
"""

adapter = GoTestAdapter()


def test_build_command() -> None:
    assert adapter.build_command() == ["go", "test", "./...", "-v"]
    assert adapter.build_command(["-run", "TestDivide"]) == [
        "go",
        "test",
        "-v",
        "-run",
        "TestDivide",
    ]


def test_parse_failure() -> None:
    result = adapter.parse_result(
        ExecResult(returncode=1, stdout=_GO_FAIL, stderr="", duration_s=0.003),
        workspace="/workspace",
    )
    assert result.framework is Framework.GO_TEST
    assert result.outcome is Outcome.FAILED
    assert result.passed == 1
    assert result.failed == 1
    assert len(result.failures) == 1

    failure = result.failures[0]
    assert failure.nodeid == "TestDivide"
    assert "want error" in failure.message
    inner = failure.innermost_frame
    assert inner is not None
    assert inner.file == "calc_test.go"
    assert inner.line == 12


def test_parse_pass() -> None:
    result = adapter.parse_result(
        ExecResult(returncode=0, stdout=_GO_PASS, stderr="", duration_s=0.002)
    )
    assert result.outcome is Outcome.PASSED
    assert result.passed == 1


def test_parse_no_tests() -> None:
    result = adapter.parse_result(
        ExecResult(returncode=0, stdout=_GO_NO_TESTS, stderr="", duration_s=0.0)
    )
    assert result.outcome is Outcome.NO_TESTS


def test_parse_compile_error() -> None:
    result = adapter.parse_result(
        ExecResult(returncode=2, stdout="", stderr=_GO_COMPILE_ERR, duration_s=0.0),
        workspace="/workspace",
    )
    assert result.outcome is Outcome.ERROR
    assert result.errors == 1
    assert "undefined: foo" in result.failures[0].message


def test_panic_frames_attach_function() -> None:
    frames = adapter.parse_frames(_GO_PANIC, "/workspace")
    by_file = {f.file: f for f in frames}
    assert "calc.go" in by_file
    assert by_file["calc.go"].line == 8
    assert by_file["calc.go"].function == "example/calc.Divide"
