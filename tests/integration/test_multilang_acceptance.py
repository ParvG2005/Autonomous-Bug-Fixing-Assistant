"""Phase 8 acceptance: a verified fix in each of Python, JS/TS, and Go.

For every language we run the *real* runner pipeline (detect → execute in the
local sandbox → parse): a buggy project fails, the one-line fix is applied, and
the same suite then passes. This is the build-plan acceptance ("a verified fix
in each of Python, JS/TS, Go") exercised end-to-end through the language
adapters, without a model in the loop.

Python runs unconditionally (the toolchain is always present). The JS and Go
cases skip when their toolchain is missing from the host, mirroring how the PR
acceptance skips without GitHub creds.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.runner import Outcome, run_tests
from app.sandbox import LocalSandbox, ResourceLimits

_LIMITS = ResourceLimits(timeout_s=120.0)


def _verify_red_then_green(
    workspace: Path, buggy: dict[str, str], fix: tuple[str, str, str]
) -> None:
    for name, content in buggy.items():
        (workspace / name).write_text(content, encoding="utf-8")

    red = run_tests(workspace, LocalSandbox(), limits=_LIMITS)
    assert red.outcome is Outcome.FAILED, (
        f"expected red, got {red.outcome}: {red.stdout}{red.stderr}"
    )
    assert red.failed >= 1

    filename, old, new = fix
    path = workspace / filename
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    # The local sandbox runs in-place; CPython keys its bytecode cache on the
    # source mtime (second granularity), so a sub-second re-run can import stale
    # .pyc. Drop the cache so the fix is actually picked up. (No-op for JS/Go.)
    for cache in workspace.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    green = run_tests(workspace, LocalSandbox(), limits=_LIMITS)
    assert green.outcome is Outcome.PASSED, (
        f"expected green, got {green.outcome}: {green.stdout}{green.stderr}"
    )
    assert green.ok


def test_python_verified_fix(tmp_path: Path) -> None:
    _verify_red_then_green(
        tmp_path,
        {
            "calc.py": "def add(a, b):\n    return a - b\n",
            "test_calc.py": (
                "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
            ),
        },
        ("calc.py", "return a - b", "return a + b"),
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node toolchain not installed")
def test_javascript_verified_fix(tmp_path: Path) -> None:
    _verify_red_then_green(
        tmp_path,
        {
            "calc.js": "function add(a, b) { return a - b; }\nmodule.exports = { add };\n",
            "calc.test.js": (
                "const { test } = require('node:test');\n"
                "const assert = require('node:assert');\n"
                "const { add } = require('./calc');\n\n"
                "test('add', () => { assert.strictEqual(add(2, 3), 5); });\n"
            ),
        },
        ("calc.js", "return a - b", "return a + b"),
    )


@pytest.mark.skipif(shutil.which("go") is None, reason="go toolchain not installed")
def test_go_verified_fix(tmp_path: Path) -> None:
    _verify_red_then_green(
        tmp_path,
        {
            "go.mod": "module example/calc\n\ngo 1.21\n",
            "calc.go": "package calc\n\nfunc Add(a, b int) int {\n\treturn a - b\n}\n",
            "calc_test.go": (
                'package calc\n\nimport "testing"\n\n'
                "func TestAdd(t *testing.T) {\n"
                "\tif Add(2, 3) != 5 {\n"
                '\t\tt.Errorf("Add(2, 3) = %d; want 5", Add(2, 3))\n'
                "\t}\n}\n"
            ),
        },
        ("calc.go", "return a - b", "return a + b"),
    )
