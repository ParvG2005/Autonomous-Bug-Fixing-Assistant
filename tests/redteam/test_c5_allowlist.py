"""C5 — Tool-call allowlist enforcement; §5 category 7 (bypass / traversal / fuzz).

Default-deny: an unknown tool, a disallowed command, a traversal path, or a
malformed argument shape is rejected before anything executes. Proven directly on
the ``Allowlist`` primitive and through the ``ToolExecutor`` dispatcher.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.tools import ToolExecutor
from app.core.allowlist import Allowlist, ToolNotAllowed
from app.index.repo_brain import RepoBrain
from app.sandbox import LocalSandbox, ResourceLimits

from .conftest import MALICIOUS_ARGV

pytestmark = pytest.mark.redteam


def _executor(root: Path) -> ToolExecutor:
    return ToolExecutor(
        root, RepoBrain(root), LocalSandbox(), limits=ResourceLimits(timeout_s=30.0)
    )


# --- the primitive, directly ---------------------------------------------------


def test_unknown_tool_rejected() -> None:
    with pytest.raises(ToolNotAllowed):
        Allowlist().check_tool("exfiltrate")


@pytest.mark.parametrize("argv", MALICIOUS_ARGV)
def test_disallowed_commands_rejected(argv: list[str]) -> None:
    with pytest.raises(ToolNotAllowed):
        Allowlist().check_command(argv)


def test_empty_argv_rejected() -> None:
    with pytest.raises(ToolNotAllowed):
        Allowlist().check_command([])


def test_only_the_documented_commands_are_allowed() -> None:
    # Lock the surface: an accidental widening of the command set fails here.
    assert Allowlist().commands == frozenset(
        {"python", "pytest", "pip", "node", "npm", "npx", "go", "ls"}
    )


# --- through the dispatcher (default-deny end to end) --------------------------


def test_dispatch_unknown_tool_is_error_not_crash(failing_project: Path) -> None:
    ex = _executor(failing_project)
    text, is_error = ex.dispatch("delete_repo", {})
    assert is_error and "not allowlisted" in text


@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd", "../../../root/.ssh/id_rsa"])
def test_path_traversal_rejected_on_read_and_edit(failing_project: Path, path: str) -> None:
    ex = _executor(failing_project)
    _r_text, r_err = ex.dispatch("read_file", {"path": path})
    assert r_err
    _e_text, e_err = ex.dispatch("edit_file", {"path": path, "old_str": "", "new_str": "x"})
    assert e_err


def test_argument_fuzz_never_bypasses(failing_project: Path) -> None:
    """Malformed argument shapes are reported as errors, never executed or raised."""
    ex = _executor(failing_project)
    fuzz: list[tuple[str, dict[str, object]]] = [
        ("run_command", {}),  # missing argv
        ("run_command", {"argv": "git push"}),  # str, not list
        ("run_command", {"argv": [1, 2, 3]}),  # non-str argv -> "1" not allowlisted
        ("read_file", {}),  # missing path
        ("read_file", {"path": 123}),
        ("edit_file", {"path": "x"}),  # missing old/new
        ("find_symbol", {}),  # missing name
        ("search", {}),  # missing pattern
    ]
    for name, args in fuzz:
        _text, is_error = ex.dispatch(name, args)
        assert is_error, f"{name}{args} should be refused"
    # The workspace is unchanged: no edit slipped through.
    assert ex.edits == []
