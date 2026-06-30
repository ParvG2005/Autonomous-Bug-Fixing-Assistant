"""SWE-bench-lite loader — gated behind the dataset + network (like Phase 5/8).

The offline-tested core of the harness is the **custom** suite. SWE-bench-lite is
wired here but not run in CI: each instance points at a real GitHub repo + base
commit, so materializing a case **clones the repo** (network egress) and applies
the instance's ``test_patch`` (which adds the failing test the fix must turn
green). Parsing the dataset is offline-testable; materialization is integration.

Get the dataset as a JSONL (one instance per line), e.g. exported from the
``princeton-nlp/SWE-bench_Lite`` HF dataset, then::

    bugfix-eval run --suite swebench-lite --jsonl path/to/swe_bench_lite.jsonl --confirm

Each instance row carries at least: ``instance_id``, ``repo`` (``owner/name``),
``base_commit``, ``problem_statement``, ``test_patch``.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eval.dataset import EvalCase

SWEBENCH_LITE_SUITE = "swebench-lite"
_GITHUB = "https://github.com"

Run = Callable[..., subprocess.CompletedProcess[bytes]]


@dataclass(frozen=True)
class SweBenchInstance:
    """One SWE-bench-lite row, reduced to what the harness needs."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    test_patch: str

    def issue_text(self) -> str:
        """The issue text handed to the agent (the upstream problem statement)."""
        return self.problem_statement.strip()


def load_instances(jsonl_path: Path, *, limit: int | None = None) -> list[SweBenchInstance]:
    """Parse a SWE-bench-lite JSONL into instances (offline; no clone)."""
    if not jsonl_path.is_file():
        raise FileNotFoundError(
            f"SWE-bench-lite dataset not found at {jsonl_path}. Export the "
            "princeton-nlp/SWE-bench_Lite split to JSONL first (see eval/swebench.py)."
        )
    instances: list[SweBenchInstance] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        instances.append(
            SweBenchInstance(
                instance_id=str(row["instance_id"]),
                repo=str(row["repo"]),
                base_commit=str(row["base_commit"]),
                problem_statement=str(row.get("problem_statement", "")),
                test_patch=str(row.get("test_patch", "")),
            )
        )
        if limit is not None and len(instances) >= limit:
            break
    return instances


def _git(run: Run, *args: str, cwd: Path | None = None) -> None:
    proc = run(["git", *args], cwd=str(cwd) if cwd else None, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace')}")


def materialize_instance(inst: SweBenchInstance, dest: Path, *, run: Run = subprocess.run) -> None:
    """Clone ``inst``'s repo at its base commit into ``dest`` and apply the test patch.

    NETWORK: clones from GitHub. Integration-only — not exercised in CI. ``run`` is
    injected so the git calls can be faked in a unit test without touching the wire.
    """
    dest.mkdir(parents=True, exist_ok=True)
    _git(run, "init", "-q", cwd=dest)
    _git(run, "remote", "add", "origin", f"{_GITHUB}/{inst.repo}.git", cwd=dest)
    _git(run, "fetch", "-q", "--depth", "1", "origin", inst.base_commit, cwd=dest)
    _git(run, "checkout", "-q", "FETCH_HEAD", cwd=dest)
    if inst.test_patch.strip():
        patch_file = dest / ".swebench_test.patch"
        patch_file.write_text(inst.test_patch, encoding="utf-8")
        _git(run, "apply", str(patch_file), cwd=dest)
        patch_file.unlink()


def load_swebench_lite(
    jsonl_path: Path, *, limit: int | None = None, run: Run = subprocess.run
) -> list[EvalCase]:
    """Build :class:`~eval.dataset.EvalCase` objects backed by repo clones (gated)."""
    cases: list[EvalCase] = []
    for inst in load_instances(jsonl_path, limit=limit):

        def _setup(dest: Path, _inst: SweBenchInstance = inst) -> None:
            materialize_instance(_inst, dest, run=run)

        cases.append(
            EvalCase(
                id=inst.instance_id,
                issue_text=inst.issue_text(),
                language="python",
                setup=_setup,
            )
        )
    return cases
