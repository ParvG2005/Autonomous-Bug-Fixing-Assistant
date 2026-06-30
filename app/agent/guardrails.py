"""Edit guardrails: flag sensitive files and cap the diff size (Phase 4).

The spec is explicit: the agent must *flag* — never silently edit — CI config,
lockfiles, and anything holding secrets, and must not produce an unbounded diff.
These are enforced at the edit boundary (:mod:`app.agent.tools`): a sensitive
edit is refused and surfaced to the model as an error (a recorded flag), and an
edit that would push the cumulative diff past the budget is likewise refused.

Classification is by path, not content — fast, deterministic, and reviewable.
A refusal is a guardrail working, not a failure: the model is told why and can
choose a different, legitimate fix site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Default cap on the cumulative changed lines (added + removed) of a fix. A real
# bug fix is small; a large diff usually means the agent went off the rails.
DEFAULT_MAX_DIFF_LINES = 200


@dataclass(frozen=True)
class SensitivePath:
    """Why a path is off-limits to silent edits."""

    kind: str  # "ci-config" | "lockfile" | "secret"
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


class DiffTooLarge(Exception):
    """Raised when an edit would push the cumulative diff past the budget."""


# --- classification rules --------------------------------------------------

# CI / pipeline configuration (editing these can change what runs on push).
_CI_DIR_PREFIXES = (".github/workflows/", ".circleci/")
_CI_EXACT = {".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml", "Jenkinsfile"}

# Dependency lockfiles (pinned, machine-managed; never hand-edited by the agent).
_LOCKFILES = {
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    "Gemfile.lock",
}

# Secret-bearing files. ``.env`` and variants, private keys, credential bundles.
_SECRET_EXACT = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials"}
_SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12")
_SECRET_NAME_RE = re.compile(r"^\.env(\..+)?$|secrets?\.[\w.]+$", re.IGNORECASE)


def _basename(rel_path: str) -> str:
    return rel_path.replace("\\", "/").rsplit("/", 1)[-1]


def sensitive_reason(rel_path: str) -> SensitivePath | None:
    """Return why ``rel_path`` is sensitive, or ``None`` if it is ordinary source."""
    norm = rel_path.replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    base = _basename(norm)

    if norm.startswith(_CI_DIR_PREFIXES) or base in _CI_EXACT:
        return SensitivePath("ci-config", f"{rel_path} controls CI/CD")
    if base in _LOCKFILES:
        return SensitivePath("lockfile", f"{rel_path} is a dependency lockfile")
    if base in _SECRET_EXACT or base.endswith(_SECRET_SUFFIXES) or _SECRET_NAME_RE.match(base):
        return SensitivePath("secret", f"{rel_path} may hold secrets")
    return None


def diff_changed_lines(diff: str) -> int:
    """Count added/removed lines in a unified diff, excluding file headers."""
    count = 0
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            count += 1
    return count


def check_diff_budget(diff: str, *, max_lines: int = DEFAULT_MAX_DIFF_LINES) -> None:
    """Raise :class:`DiffTooLarge` if ``diff`` exceeds ``max_lines`` changed lines."""
    changed = diff_changed_lines(diff)
    if changed > max_lines:
        raise DiffTooLarge(f"diff has {changed} changed lines, over the {max_lines}-line budget")
