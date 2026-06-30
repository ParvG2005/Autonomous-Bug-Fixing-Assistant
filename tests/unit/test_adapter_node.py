"""Parsing captured `node --test --test-reporter=tap` output."""

from __future__ import annotations

from app.runner.adapters.javascript import NodeTestAdapter
from app.runner.models import Framework, Outcome
from app.sandbox.models import ExecResult

# Real TAP output (paths rewritten to the sandbox mount /workspace): one pass,
# one failure with an assertion error block + V8 stack.
_TAP_FAIL = """\
TAP version 13
# Subtest: add works
ok 1 - add works
  ---
  duration_ms: 0.47
  type: 'test'
  ...
# Subtest: divide by zero
not ok 2 - divide by zero
  ---
  duration_ms: 0.48
  type: 'test'
  location: '/workspace/calc.test.js:6:1'
  failureType: 'testCodeFailure'
  error: |-
    Expected values to be strictly equal:

    Infinity !== 0

  code: 'ERR_ASSERTION'
  name: 'AssertionError'
  stack: |-
    TestContext.<anonymous> (/workspace/calc.test.js:6:39)
    Test.run (node:internal/test_runner/test:1382:25)
    async startSubtestAfterBootstrap (node:internal/test_runner/harness:387:3)
  ...
1..2
# tests 2
# suites 0
# pass 1
# fail 1
# cancelled 0
# skipped 0
# todo 0
# duration_ms 59.6
"""

_TAP_PASS = """\
TAP version 13
# Subtest: add works
ok 1 - add works
  ---
  duration_ms: 0.4
  ...
1..1
# tests 1
# pass 1
# fail 0
"""

_TAP_NO_TESTS = """\
TAP version 13
1..0
# tests 0
# pass 0
# fail 0
"""

adapter = NodeTestAdapter()


def test_build_command_forces_tap() -> None:
    assert adapter.build_command() == ["node", "--test", "--test-reporter=tap"]
    assert adapter.build_command(["a.test.js"]) == [
        "node",
        "--test",
        "--test-reporter=tap",
        "a.test.js",
    ]


def test_parse_failure() -> None:
    result = adapter.parse_result(
        ExecResult(returncode=1, stdout=_TAP_FAIL, stderr="", duration_s=0.06),
        workspace="/workspace",
    )
    assert result.framework is Framework.NODE_TEST
    assert result.outcome is Outcome.FAILED
    assert result.passed == 1
    assert result.failed == 1
    assert len(result.failures) == 1

    failure = result.failures[0]
    assert failure.nodeid == "divide by zero"
    assert "strictly equal" in failure.message
    inner = failure.innermost_frame
    assert inner is not None
    assert inner.file == "calc.test.js"
    assert inner.line == 6


def test_parse_pass() -> None:
    result = adapter.parse_result(
        ExecResult(returncode=0, stdout=_TAP_PASS, stderr="", duration_s=0.01)
    )
    assert result.outcome is Outcome.PASSED
    assert result.ok
    assert result.passed == 1


def test_parse_no_tests() -> None:
    result = adapter.parse_result(
        ExecResult(returncode=1, stdout=_TAP_NO_TESTS, stderr="", duration_s=0.01)
    )
    assert result.outcome is Outcome.NO_TESTS


def test_parse_timeout() -> None:
    result = adapter.parse_result(
        ExecResult(returncode=-1, stdout="", stderr="", duration_s=120.0, timed_out=True)
    )
    assert result.outcome is Outcome.TIMEOUT


def test_frames_ignore_node_internals() -> None:
    frames = adapter.parse_frames(_TAP_FAIL, "/workspace")
    # Only user-code frames (calc.test.js), never node:internal/* frames.
    assert frames
    assert all(f.file == "calc.test.js" for f in frames)
