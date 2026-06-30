"""The language-adapter contract (Phase 8).

Before Phase 8 the runner was hard-wired to pytest. A :class:`LanguageAdapter`
factors out everything that is language/framework-specific so the rest of the
system (the agent loop, the worker pipeline) stays language-agnostic:

* **detect** — does this workspace use my framework?
* **install_command** — how to install the target repo's deps (or ``None``);
* **build_command** — the deterministic test invocation;
* **parse_frames** — pull ``{file, line, function}`` frames out of this
  language's stack traces;
* **parse_result** — turn a raw :class:`~app.sandbox.models.ExecResult` into a
  normalized :class:`~app.runner.models.TestRunResult`.

Each adapter also declares the sandbox ``image`` it needs and the ``commands``
its test/install invocations require on the ``run_command`` allowlist. Adapters
are registered in :mod:`app.runner.adapters` and selected by
:func:`~app.runner.adapters.detect_adapter`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from app.runner.models import Framework, TestRunResult, TraceFrame
from app.sandbox.models import ExecResult


@runtime_checkable
class LanguageAdapter(Protocol):
    """One language/test-framework plug-in. All methods are pure except that
    nothing here touches the network or the sandbox — execution is the runner's
    job; the adapter only decides *what* to run and *how* to read the output."""

    framework: Framework
    # The sandbox base image carrying this language's toolchain.
    image: str
    # argv[0]s this adapter's build/install commands need allowlisted for
    # ``run_command`` (e.g. ``{"go"}``, ``{"node", "npm"}``).
    commands: frozenset[str]

    def detect(self, workspace: Path) -> bool:
        """True when ``workspace`` is a project this adapter can test."""
        ...

    def install_command(self, workspace: Path) -> list[str] | None:
        """Command to install the target repo's deps, or ``None`` if not needed.

        Returns ``None`` when the project is dependency-free or its deps are
        already present (so the runner can skip a network round-trip). The
        runner only runs this when explicitly asked (deps install needs egress,
        which the sandbox denies by default).
        """
        ...

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        """The test invocation, optionally restricted to ``targets``."""
        ...

    def parse_frames(self, text: str, workspace: str | Path | None = None) -> list[TraceFrame]:
        """Extract stack-trace frames from ``text`` (workspace-relative when inside)."""
        ...

    def parse_result(
        self, exec_result: ExecResult, workspace: str | Path | None = None
    ) -> TestRunResult:
        """Normalize a raw run into a :class:`TestRunResult`.

        ``workspace`` is the mount point inside the run environment, used to
        relativize frame paths.
        """
        ...
