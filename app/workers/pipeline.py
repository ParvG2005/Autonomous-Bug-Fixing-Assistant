"""The job pipeline (Phase 7) — drives one job through the state machine.

Given a queued job id, this:

1. ``queued -> running`` and records the start (durable, so a crash mid-run is
   visible to the startup sweep).
2. Clones the repo into an **isolated per-job workspace** and runs the Phase 4
   ``solve_issue`` pipeline inside the sandbox (one container per job).
3. Persists the outcome — :class:`Run` rows per phase, the diff + reasoning
   :class:`Artifact` rows, and the :class:`Fix` — then routes to the human gate:
   a resolved fix goes ``running -> awaiting_approval`` (never auto-published —
   SECURITY.md C1); an unresolved attempt or any error goes ``running -> failed``.

Every external dependency (the model client, the workspace clone, the sandbox,
and even ``solve_issue`` itself) is injectable, so the whole pipeline runs
offline against a scripted fake client + a :class:`LocalSandbox` + a local
fixture clone — no Redis, no Docker, no network.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import select

from app.agent.loop import CreateMessage
from app.agent.models import AgentBudget
from app.agent.solve import SolveResult, solve_issue
from app.core.settings import Settings
from app.db.repos import repo_clone_url
from app.db.session import Database
from app.index.clone import clone_repo, fetch_pr_head
from app.models.entities import (
    Artifact,
    ArtifactKind,
    ArtifactStorage,
    Fix,
    Job,
    JobState,
    Repo,
    Run,
    RunPhase,
    RunStatus,
)
from app.sandbox.base import Sandbox
from app.telemetry.cost import cost_breakdown
from app.telemetry.logging import get_logger
from app.telemetry.tracing import Tracer, build_trace, get_tracer
from app.workers.progress import record_log
from app.workers.state import transition

log = get_logger("workers.pipeline")


@dataclass(frozen=True)
class RepoInfo:
    """Primitive repo fields, lifted out of the ORM so they cross session scopes."""

    full_name: str
    default_branch: str
    clone_url: str
    ref: str | None = None
    pr_number: int | None = None


class PrepareWorkspace(Protocol):
    """Clone (or otherwise materialize) ``repo`` into ``dest`` and return the path."""

    def __call__(self, repo: RepoInfo, dest: Path) -> Path: ...


# A solve callable matching :func:`app.agent.solve.solve_issue` (the injectable seam).
SolveFn = Callable[..., SolveResult]


def _default_prepare_workspace(repo: RepoInfo, dest: Path) -> Path:
    workspace = clone_repo(repo.clone_url, dest, depth=1, ref=repo.ref or repo.default_branch)
    if repo.pr_number is not None:
        fetch_pr_head(workspace, repo.pr_number)
    return workspace


def _is_new_test_file(path: str) -> bool:
    name = Path(path).name
    return name.startswith("test_") or name.endswith("_test.py")


def _artifact(job_id: object, kind: ArtifactKind, content: str) -> Artifact:
    import hashlib

    body = content.encode("utf-8")
    return Artifact(
        job_id=job_id,
        kind=kind,
        storage=ArtifactStorage.INLINE_SMALL,
        content=content,
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
    )


async def _start(db: Database, job_id: str) -> tuple[RepoInfo, str, str | None, AgentBudget] | None:
    """Claim a queued job: ``queued -> running``. Returns run inputs, or ``None`` to skip."""
    async with db.session() as session:
        job = (
            await session.execute(select(Job).where(Job.id == _as_uuid(job_id)))
        ).scalar_one_or_none()
        if job is None:
            log.warning("pipeline_no_job", job_id=job_id)
            return None
        if job.state is not JobState.QUEUED:
            # Already claimed / terminal — dedup or a stale re-enqueue. Skip cleanly.
            log.info("pipeline_skip", job_id=job_id, state=job.state.value)
            return None

        repo = (await session.execute(select(Repo).where(Repo.id == job.repo_id))).scalar_one()
        repo_info = RepoInfo(
            full_name=repo.full_name,
            default_branch=repo.default_branch,
            clone_url=repo_clone_url(repo),
            ref=job.ref,
            pr_number=job.pr_number,
        )

        body = ""
        if job.issue_body_ref is not None:
            artifact = (
                await session.execute(select(Artifact).where(Artifact.id == job.issue_body_ref))
            ).scalar_one_or_none()
            body = (artifact.content if artifact else "") or ""

        title = job.issue_title
        b = job.budget or {}
        budget = AgentBudget(
            max_iterations=int(b.get("max_iterations", 20)),
            max_tokens=int(b.get("max_tokens", 400_000)),
            deadline_s=float(b.get("deadline_s", 600.0)),
        )

        transition(job, JobState.RUNNING)
        await record_log(session, job.id, f"running: cloning {repo_info.full_name}")
    return repo_info, body, title, budget


async def _persist_success(
    db: Database,
    job_id: str,
    result: SolveResult,
    *,
    model: str,
    tracer: Tracer,
) -> JobState:
    async with db.session() as session:
        job = (await session.execute(select(Job).where(Job.id == _as_uuid(job_id)))).scalar_one()
        repo = (await session.execute(select(Repo).where(Repo.id == job.repo_id))).scalar_one()

        agent = result.agent
        metrics = {
            "iterations": agent.iterations,
            "input_tokens": agent.usage.input_tokens,
            "output_tokens": agent.usage.output_tokens,
        }

        # Phase 10: build the replayable trace, mirror it to Langfuse (no-op
        # offline), and stamp the external id on the authoritative verify run.
        trace = build_trace(result, model=model)
        trace_id = tracer.emit(trace, name=f"job:{job_id}")

        session.add(
            Run(
                job_id=job.id,
                phase=RunPhase.LOCALIZE,
                status=RunStatus.OK,
                metrics={"suspects": len(result.suspects)},
            )
        )
        session.add(
            Run(
                job_id=job.id,
                phase=RunPhase.FIX,
                status=RunStatus.OK if agent.edits else RunStatus.FAIL,
                metrics=metrics,
            )
        )
        session.add(
            Run(
                job_id=job.id,
                phase=RunPhase.VERIFY,
                status=RunStatus.OK if result.resolved else RunStatus.FAIL,
                langfuse_trace_id=trace_id,
                metrics={"resolved": result.resolved, "stop_reason": agent.stop_reason.value},
            )
        )

        diff_artifact = _artifact(job.id, ArtifactKind.DIFF, agent.diff)
        reasoning_artifact = _artifact(job.id, ArtifactKind.REASONING, result.writeup)
        trace_artifact = _artifact(
            job.id, ArtifactKind.TRACE, json.dumps(trace, indent=2, sort_keys=True)
        )
        artifacts_to_add = [diff_artifact, reasoning_artifact, trace_artifact]

        bundle_artifact = None
        if agent.edits:
            from app.vcs.bundle import build_fix_bundle
            from app.vcs.models import RepoRef

            owner, _, name = repo.full_name.partition("/")
            bundle = build_fix_bundle(
                job_id=str(job.id),
                # `installation_id or 0` is a harmless placeholder: the publish
                # path (Task 11) re-reads the live Repo.installation_id and
                # refuses when it is null, so the stored 0 is never used to
                # mint a token.
                repo=RepoRef(owner=owner, name=name, installation_id=repo.installation_id or 0),
                base_branch=repo.default_branch,
                result=result,
            )
            bundle_json = json.dumps(
                {
                    "job_id": bundle.job_id,
                    "repo": {
                        "owner": owner,
                        "name": name,
                        "installation_id": repo.installation_id or 0,
                    },
                    "base_branch": bundle.base_branch,
                    "head_branch": bundle.head_branch,
                    "title": bundle.title,
                    "commit_message": bundle.commit_message,
                    "body": bundle.body,
                    "changes": [{"path": c.path, "content": c.content} for c in bundle.changes],
                    "reasoning_comment": bundle.reasoning_comment,
                },
                indent=2,
            )
            bundle_artifact = _artifact(job.id, ArtifactKind.BUNDLE, bundle_json)
            artifacts_to_add.append(bundle_artifact)

        session.add_all(artifacts_to_add)
        await session.flush()

        wrote_repro = any(e.before == "" and _is_new_test_file(e.path) for e in agent.edits)
        session.add(
            Fix(
                job_id=job.id,
                diff_artifact_id=diff_artifact.id,
                reasoning_artifact_id=reasoning_artifact.id,
                diff_lines_added=result.summary.insertions,
                diff_lines_removed=result.summary.deletions,
                wrote_repro_test=wrote_repro,
                flags={"guardrail": result.flags},
                tests_pass=result.resolved,
            )
        )

        job.cost = {
            **cost_breakdown(model, agent.usage.input_tokens, agent.usage.output_tokens),
            "iterations": agent.iterations,
        }

        if result.resolved:
            transition(job, JobState.AWAITING_APPROVAL)
            await record_log(
                session,
                job.id,
                f"fix verified ({result.summary}); awaiting human approval",
            )
        else:
            transition(job, JobState.FAILED, reason=f"unresolved: {agent.stop_reason.value}")
            await record_log(session, job.id, f"failed: {agent.stop_reason.value}")
        return job.state


async def _fail(db: Database, job_id: str, reason: str) -> JobState:
    async with db.session() as session:
        job = (
            await session.execute(select(Job).where(Job.id == _as_uuid(job_id)))
        ).scalar_one_or_none()
        if job is None or job.state in (JobState.DONE, JobState.FAILED, JobState.REJECTED):
            return job.state if job else JobState.FAILED
        transition(job, JobState.FAILED, reason=reason)
        await record_log(session, job.id, f"failed: {reason}")
        return JobState.FAILED


def _as_uuid(job_id: str) -> object:
    import uuid

    return uuid.UUID(job_id) if isinstance(job_id, str) else job_id


async def _current_state(db: Database, job_id: str) -> JobState:
    async with db.session() as session:
        job = (
            await session.execute(select(Job).where(Job.id == _as_uuid(job_id)))
        ).scalar_one_or_none()
        return job.state if job is not None else JobState.FAILED


async def run_pipeline(
    db: Database,
    job_id: str,
    *,
    create_message: CreateMessage,
    settings: Settings,
    prepare_workspace: PrepareWorkspace | None = None,
    sandbox: Sandbox | None = None,
    solve: SolveFn | None = None,
    tracer: Tracer | None = None,
    keep_workspace: bool = False,
) -> JobState:
    """Run one job end to end and return its final state.

    Errors are caught and recorded as ``failed`` (the job is not retried in a
    tight loop); a *process* crash is handled separately by the startup sweep.
    """
    prepare_workspace = prepare_workspace or _default_prepare_workspace
    solve = solve or solve_issue
    tracer = tracer or get_tracer(settings)

    claimed = await _start(db, job_id)
    if claimed is None:
        return await _current_state(db, job_id)  # skipped: report the row's actual state
    repo_info, body, title, budget = claimed

    dest = (settings.workspace_root / job_id).resolve()
    try:
        if dest.exists():
            shutil.rmtree(dest)  # re-entrant: a replayed job starts from a clean clone
        workspace = await asyncio.to_thread(prepare_workspace, repo_info, dest)

        result = await asyncio.to_thread(
            solve,
            workspace,
            body,
            create_message,
            model=settings.agent_model,
            title=title,
            sandbox=sandbox,
            budget=budget,
        )
        return await _persist_success(db, job_id, result, model=settings.agent_model, tracer=tracer)
    except Exception as exc:
        log.error("pipeline_error", job_id=job_id, error=str(exc))
        return await _fail(db, job_id, f"{type(exc).__name__}: {exc}")
    finally:
        if not keep_workspace and dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
