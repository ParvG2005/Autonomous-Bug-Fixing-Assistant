"""Unit tests for the tool dispatcher and allowlist enforcement (offline).

Uses the real RepoBrain + LocalSandbox against the on-disk fixtures — no
Anthropic API and no Docker required.
"""

from __future__ import annotations

from pathlib import Path

from app.agent.tools import ToolExecutor, tool_schemas
from app.core.allowlist import Allowlist
from app.index.repo_brain import RepoBrain
from app.sandbox import LocalSandbox, ResourceLimits


def _executor(root: Path, **kwargs: object) -> ToolExecutor:
    return ToolExecutor(
        root,
        RepoBrain(root),
        LocalSandbox(),
        limits=ResourceLimits(timeout_s=60.0),
        **kwargs,  # type: ignore[arg-type]
    )


def test_tool_schemas_cover_the_six_tools() -> None:
    names = {t["name"] for t in tool_schemas()}
    assert names == {
        "read_file",
        "search",
        "find_symbol",
        "edit_file",
        "run_tests",
        "run_command",
    }


def test_read_file_tool(workspace: Path) -> None:
    ex = _executor(workspace)
    text, is_error = ex.dispatch("read_file", {"path": "sample.py", "start_line": 1, "end_line": 5})
    assert not is_error
    assert "def greet" in text
    assert ex.tool_calls[-1].name == "read_file"


def test_search_tool(workspace: Path) -> None:
    ex = _executor(workspace)
    text, is_error = ex.dispatch("search", {"pattern": "def greet", "fixed": True})
    assert not is_error
    assert "sample.py" in text


def test_find_symbol_tool(workspace: Path) -> None:
    ex = _executor(workspace)
    text, is_error = ex.dispatch("find_symbol", {"name": "Greeter"})
    assert not is_error
    assert "Greeter" in text


def test_edit_file_tool_records_edit(workspace: Path) -> None:
    ex = _executor(workspace)
    _text, is_error = ex.dispatch(
        "edit_file",
        {"path": "sample.py", "old_str": 'return f"hello {name}"', "new_str": "return name"},
    )
    assert not is_error
    assert len(ex.edits) == 1
    assert "return name" in (workspace / "sample.py").read_text()


def test_edit_file_error_is_reported_not_raised(workspace: Path) -> None:
    ex = _executor(workspace)
    text, is_error = ex.dispatch(
        "edit_file", {"path": "sample.py", "old_str": "nonexistent", "new_str": "x"}
    )
    assert is_error
    assert text.startswith("error:")


def test_run_tests_tool(failing_project: Path) -> None:
    ex = _executor(failing_project)
    text, is_error = ex.dispatch("run_tests", {})
    assert not is_error
    assert "failed=2" in text
    assert ex.last_test_result is not None


def test_run_command_allowlisted(workspace: Path) -> None:
    ex = _executor(workspace)
    text, is_error = ex.dispatch("run_command", {"argv": ["python", "-c", "print('hi')"]})
    assert not is_error
    assert "hi" in text


def test_run_command_rejects_disallowed_command(workspace: Path) -> None:
    ex = _executor(workspace)
    text, is_error = ex.dispatch("run_command", {"argv": ["rm", "-rf", "/"]})
    assert is_error
    assert "not allowlisted" in text


def test_dispatch_rejects_disallowed_tool(workspace: Path) -> None:
    # An allowlist without edit_file must reject it before any file is touched.
    restricted = Allowlist(tools=frozenset({"read_file"}))
    ex = _executor(workspace, allowlist=restricted)
    text, is_error = ex.dispatch("edit_file", {"path": "sample.py", "old_str": "x", "new_str": "y"})
    assert is_error
    assert "not allowlisted" in text
    assert ex.edits == []
