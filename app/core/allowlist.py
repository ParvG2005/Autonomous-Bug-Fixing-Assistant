"""Tool-call allowlist primitives.

Every agent tool call is validated here *before* dispatch (ARCHITECTURE.md §6).
A rejected call returns an error to the model and is never executed. Phase 3
wires this in front of tool dispatch; the scaffold defines the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class ToolNotAllowed(Exception):
    """Raised when a tool call fails allowlist validation."""


@dataclass(frozen=True)
class Allowlist:
    """The set of tools (and shell commands) the agent may invoke."""

    tools: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"read_file", "search", "find_symbol", "edit_file", "run_tests", "run_command"}
        )
    )
    # Commands permitted via ``run_command`` (exact argv[0] match). Covers every
    # language adapter's test/install toolchain (Phase 8): pytest/pip (Python),
    # node/npm/npx (JS/TS), go (Go), plus the read-only `ls`.
    commands: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"python", "pytest", "pip", "node", "npm", "npx", "go", "ls"}
        )
    )

    def check_tool(self, name: str) -> None:
        """Raise :class:`ToolNotAllowed` if ``name`` is not an allowed tool."""
        if name not in self.tools:
            raise ToolNotAllowed(f"tool {name!r} is not allowlisted")

    def check_command(self, argv: list[str]) -> None:
        """Raise :class:`ToolNotAllowed` if ``argv[0]`` is not an allowed command."""
        if not argv or argv[0] not in self.commands:
            raise ToolNotAllowed(f"command {argv[:1]!r} is not allowlisted")
