"""Tool schemas and the dispatcher the agent loop drives.

Six tools are exposed to the model: three read-only Phase 1 tools (``read_file``,
``search``, ``find_symbol``), the ``edit_file`` mutator, and two sandbox-backed
execution tools (``run_tests``, ``run_command``). Every call is validated against
:class:`~app.core.allowlist.Allowlist` *before* dispatch — a rejected call returns
an error string to the model and is never executed (ARCHITECTURE.md §6).

``run_command`` is additionally gated on an argv[0] allowlist, and runs inside the
sandbox (no egress, capped) exactly like ``run_tests``. Untrusted repo code never
executes outside the sandbox boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent.edit import EditError, apply_edit, unified_diff
from app.agent.guardrails import (
    DEFAULT_MAX_DIFF_LINES,
    DiffTooLarge,
    check_diff_budget,
    sensitive_reason,
)
from app.agent.models import FileEdit, ToolCall
from app.core.allowlist import Allowlist, ToolNotAllowed
from app.index.read import PathOutsideWorkspace, resolve_in_workspace
from app.index.repo_brain import RepoBrain
from app.runner.models import TestRunResult
from app.runner.pytest_runner import NoTestFramework, run_pytest
from app.sandbox.base import Sandbox
from app.sandbox.models import ResourceLimits

# Cap on the size of any single tool result fed back to the model, to protect the
# context window from a runaway read/search/command.
_MAX_RESULT_CHARS = 8000


def tool_schemas() -> list[dict[str, Any]]:
    """The Anthropic tool definitions for the six agent tools."""
    return [
        {
            "name": "read_file",
            "description": (
                "Read a file from the workspace. Use a line range for large files. "
                "Paths are relative to the workspace root."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "start_line": {"type": "integer", "description": "1-based first line."},
                    "end_line": {
                        "type": "integer",
                        "description": "1-based last line (inclusive).",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "search",
            "description": (
                "Search the workspace for a pattern (ripgrep). Returns matching "
                "lines with their file and line number."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex (or fixed) pattern."},
                    "word": {"type": "boolean", "description": "Match whole words only."},
                    "fixed": {
                        "type": "boolean",
                        "description": "Treat pattern as a literal string.",
                    },
                },
                "required": ["pattern"],
            },
        },
        {
            "name": "find_symbol",
            "description": (
                "Locate where a symbol (function, method, or class) is defined and used."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The symbol name."},
                },
                "required": ["name"],
            },
        },
        {
            "name": "edit_file",
            "description": (
                "Replace the single, unique occurrence of old_str with new_str in a "
                "file. old_str must match exactly once (add surrounding context to "
                "disambiguate). To create a new file, pass an empty old_str."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "old_str": {"type": "string", "description": "Exact text to replace."},
                    "new_str": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
        {
            "name": "run_tests",
            "description": (
                "Run the project's tests in the sandbox and return pass/fail counts "
                "plus, per failure, the message and stack frames. Optionally restrict "
                "to specific test targets (node ids or paths)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional pytest targets (e.g. 'test_calc.py::test_add').",
                    },
                },
            },
        },
        {
            "name": "run_command",
            "description": (
                "Run an allowlisted command in the sandbox (e.g. python, pytest, ls). "
                "Pass argv as a list. Network is off; output is captured."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Command and arguments, e.g. ['python', '-c', 'print(1)'].",
                    },
                },
                "required": ["argv"],
            },
        },
    ]


def _truncate(text: str) -> str:
    if len(text) <= _MAX_RESULT_CHARS:
        return text
    head = text[:_MAX_RESULT_CHARS]
    return f"{head}\n... [truncated {len(text) - _MAX_RESULT_CHARS} chars]"


def format_test_result(result: TestRunResult) -> str:
    """Render a :class:`TestRunResult` compactly for the model."""
    lines = [
        f"outcome={result.outcome.value} "
        f"passed={result.passed} failed={result.failed} "
        f"errors={result.errors} skipped={result.skipped}"
    ]
    for failure in result.failures:
        lines.append(f"\nFAILED {failure.nodeid}")
        if failure.message:
            lines.append(f"  {failure.message}")
        for frame in failure.frames:
            lines.append(f"    {frame}")
    return "\n".join(lines)


class ToolExecutor:
    """Validates and executes the agent's tool calls against one workspace.

    Holds the live trace: every :class:`ToolCall`, every :class:`FileEdit`, and the
    most recent :class:`TestRunResult` (so the loop can verify resolution).
    """

    def __init__(
        self,
        root: Path,
        brain: RepoBrain,
        sandbox: Sandbox,
        *,
        allowlist: Allowlist | None = None,
        limits: ResourceLimits | None = None,
        max_diff_lines: int = DEFAULT_MAX_DIFF_LINES,
    ) -> None:
        self.root = root.resolve()
        self.brain = brain
        self.sandbox = sandbox
        self.allowlist = allowlist or Allowlist()
        self.limits = limits or ResourceLimits()
        self.max_diff_lines = max_diff_lines
        self.tool_calls: list[ToolCall] = []
        self.edits: list[FileEdit] = []
        # Guardrail flags: sensitive-file edits the agent attempted and we refused.
        self.flags: list[str] = []
        self.last_test_result: TestRunResult | None = None

    def dispatch(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Validate and run one tool call. Returns ``(result_text, is_error)``.

        Errors (allowlist rejection, bad arguments, edit failures) are returned as
        the result with ``is_error=True`` so the model can recover, rather than
        raised — the loop must keep going.
        """
        try:
            self.allowlist.check_tool(name)
            text = self._run(name, arguments)
            is_error = False
        except (
            ToolNotAllowed,
            EditError,
            PathOutsideWorkspace,
            NoTestFramework,
            ValueError,
            KeyError,
            FileNotFoundError,
        ) as exc:
            text = f"error: {exc}"
            is_error = True

        text = _truncate(text)
        self.tool_calls.append(
            ToolCall(name=name, arguments=dict(arguments), result=text, is_error=is_error)
        )
        return text, is_error

    # --- per-tool handlers ----------------------------------------------

    def _run(self, name: str, args: dict[str, Any]) -> str:
        if name == "read_file":
            return self._read_file(args)
        if name == "search":
            return self._search(args)
        if name == "find_symbol":
            return self._find_symbol(args)
        if name == "edit_file":
            return self._edit_file(args)
        if name == "run_tests":
            return self._run_tests(args)
        if name == "run_command":
            return self._run_command(args)
        raise KeyError(f"unknown tool {name!r}")

    def _read_file(self, args: dict[str, Any]) -> str:
        path = str(args["path"])
        start = int(args.get("start_line", 1))
        end = args.get("end_line")
        sliced = self.brain.read_file(
            path, start_line=start, end_line=None if end is None else int(end)
        )
        header = f"{sliced.path} (lines {sliced.start_line}-{sliced.end_line}):\n"
        return header + sliced.text

    def _search(self, args: dict[str, Any]) -> str:
        hits = self.brain.search(
            str(args["pattern"]),
            word=bool(args.get("word", False)),
            fixed=bool(args.get("fixed", False)),
        )
        if not hits:
            return "no matches"
        return "\n".join(str(hit) for hit in hits)

    def _find_symbol(self, args: dict[str, Any]) -> str:
        lookup = self.brain.find_symbol(str(args["name"]))
        if not lookup.found:
            return f"symbol {lookup.name!r} not found"
        lines = [f"definitions of {lookup.name!r}:"]
        for sym in lookup.definitions:
            lines.append(f"  {sym.kind.value} {sym.qualified_name} at {sym.location}")
        if lookup.usages:
            lines.append(f"usages ({len(lookup.usages)}):")
            for hit in lookup.usages:
                lines.append(f"  {hit}")
        return "\n".join(lines)

    def _edit_file(self, args: dict[str, Any]) -> str:
        rel_path = str(args["path"])

        # Guardrail 1: flag — never silently edit — CI config, lockfiles, secrets.
        reason = sensitive_reason(rel_path)
        if reason is not None:
            msg = f"flagged: refusing to edit {reason}; fix a source file instead"
            self.flags.append(msg)
            raise EditError(msg)

        edit = apply_edit(self.root, rel_path, str(args["old_str"]), str(args["new_str"]))

        # Guardrail 2: keep the cumulative diff within budget. Roll back if over.
        try:
            check_diff_budget(unified_diff([*self.edits, edit]), max_lines=self.max_diff_lines)
        except DiffTooLarge as exc:
            self._rollback(edit)
            raise EditError(str(exc)) from exc

        self.edits.append(edit)
        return f"edited {edit.path}"

    def _rollback(self, edit: FileEdit) -> None:
        """Undo a just-applied edit (a new file is removed; an existing one restored)."""
        path = resolve_in_workspace(self.root, edit.path)
        if edit.before == "":  # apply_edit only creates with an empty before
            path.unlink(missing_ok=True)
        else:
            path.write_text(edit.before, encoding="utf-8")

    def _run_tests(self, args: dict[str, Any]) -> str:
        targets = args.get("targets")
        target_list = [str(t) for t in targets] if targets else None
        result = run_pytest(self.root, self.sandbox, targets=target_list, limits=self.limits)
        self.last_test_result = result
        return format_test_result(result)

    def _run_command(self, args: dict[str, Any]) -> str:
        argv = [str(a) for a in args["argv"]]
        self.allowlist.check_command(argv)
        exec_result = self.sandbox.run(argv, self.root, self.limits)
        parts = [f"returncode={exec_result.returncode}"]
        if exec_result.timed_out:
            parts.append("(timed out)")
        if exec_result.stdout:
            parts.append(f"stdout:\n{exec_result.stdout}")
        if exec_result.stderr:
            parts.append(f"stderr:\n{exec_result.stderr}")
        return "\n".join(parts)
