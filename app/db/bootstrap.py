"""``bugfix-bootstrap`` — dev startup wipe + scrape (Phase 14, dev-only).

Two guarded actions, both off the deployed path:

* ``--reset`` (the "scrap"): truncate the job-history tables to a clean slate.
  **Refuses unless ``APP_ENV=local``** — a hard guard so it can never wipe a real
  database. Leaves ``repo`` rows (installs) intact.
* ``--scrape``: list **open GitHub issues** (reusing Phase 5 App auth) and run each
  through the **same** ``ingest_labeled_issue`` path the webhook uses, with
  ``trigger="scrape"`` and capped by ``SCRAPE_MAX_JOBS``. Wipe-then-scrape is how
  the dashboard opens already populated with freshly-pulled work.

The reset + scrape *logic* is injectable and SQLite-testable; the CLI is a thin
wrapper that wires real GitHub auth. Deploy (Phase 15) uses its own
non-destructive start — none of this runs there.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import typer
from rich.console import Console
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, get_settings
from app.db.jobs import IssueRef, ingest_labeled_issue
from app.db.session import Database
from app.models.entities import (
    Approval,
    Artifact,
    Finding,
    Fix,
    Job,
    JobTrigger,
    Repo,
    Run,
    Scan,
)
from app.telemetry.logging import get_logger

app = typer.Typer(add_completion=False, help="Dev bootstrap: wipe job history and scrape issues.")
console = Console()
log = get_logger("db.bootstrap")

# Deleted children-before-parents so foreign keys never block the wipe. ``repo``
# (and its code_chunk index) are intentionally preserved — installs survive.
_RESET_ORDER = [Finding, Scan, Approval, Fix, Artifact, Run, Job]


class ResetNotAllowed(RuntimeError):
    """Raised when --reset is attempted outside APP_ENV=local."""


@dataclass(frozen=True)
class RepoIdentity:
    """The repo fields ingest needs, resolved before scraping."""

    gh_repo_id: int
    full_name: str
    installation_id: int
    default_branch: str = "main"


@dataclass(frozen=True)
class ScrapedIssue:
    """One open issue pulled from GitHub."""

    number: int
    title: str
    body: str


#: Resolve a repo full name to (identity, open issues). Injected for offline tests.
IssueSource = Callable[[str], tuple[RepoIdentity, list[ScrapedIssue]]]


async def reset_job_tables(db: Database, *, app_env: str) -> dict[str, int]:
    """Truncate job-history tables. Refuses unless ``app_env == "local"``."""
    if app_env != "local":
        raise ResetNotAllowed(
            f"--reset is only allowed when APP_ENV=local (got {app_env!r}); refusing to wipe."
        )
    counts: dict[str, int] = {}
    async with db.session() as session:
        for model in _RESET_ORDER:
            result = await session.execute(delete(model))
            counts[model.__tablename__] = int(getattr(result, "rowcount", 0) or 0)
    log.info("reset_done", **counts)
    return counts


async def scrape_repo(
    session: AsyncSession,
    identity: RepoIdentity,
    issues: list[ScrapedIssue],
    *,
    max_jobs: int,
) -> list[Job]:
    """Enqueue a scrape job for each open issue (capped at ``max_jobs``).

    Goes through ``ingest_labeled_issue`` so a scraped issue is indistinguishable
    from a webhook one downstream — idempotent per live job, untrusted body stored
    as an artifact, ``trigger="scrape"``.
    """
    jobs: list[Job] = []
    for issue in issues[: max(0, max_jobs)]:
        ref = IssueRef(
            gh_repo_id=identity.gh_repo_id,
            full_name=identity.full_name,
            installation_id=identity.installation_id,
            gh_issue_number=issue.number,
            issue_title=issue.title,
            issue_body=issue.body,
            default_branch=identity.default_branch,
        )
        result = await ingest_labeled_issue(session, ref, trigger=JobTrigger.SCRAPE)
        jobs.append(result.job)
    return jobs


async def run_bootstrap(
    db: Database,
    settings: Settings,
    *,
    reset: bool,
    scrape: bool,
    repos: list[str],
    issue_source: IssueSource | None = None,
    max_jobs: int | None = None,
) -> dict[str, object]:
    """Execute the requested wipe and/or scrape; return a summary."""
    summary: dict[str, object] = {}
    if reset:
        summary["reset"] = await reset_job_tables(db, app_env=settings.app_env)

    if scrape:
        if issue_source is None:
            raise RuntimeError("scrape requested but no issue source was provided")
        cap = settings.scrape_max_jobs if max_jobs is None else max_jobs
        scraped: dict[str, int] = {}
        async with db.session() as session:
            for full_name in repos:
                identity, issues = issue_source(full_name)
                jobs = await scrape_repo(session, identity, issues, max_jobs=cap)
                scraped[full_name] = len(jobs)
        summary["scraped"] = scraped
    return summary


# --------------------------------------------------------------------------
# Real GitHub wiring (CLI only; tests inject a fake IssueSource).
# --------------------------------------------------------------------------
def _github_issue_source(db: Database, settings: Settings, *, label: str | None) -> IssueSource:
    """Build an :class:`IssueSource` backed by the GitHub App + an installed repo.

    Identity comes from the existing ``repo`` row (preserved across --reset); the
    repo must already be installed. Issues are fetched read-only with a token
    minted for that installation.
    """
    from app.vcs.auth import mint_installation_token
    from app.vcs.github import GitHubClient
    from app.vcs.models import RepoRef

    def _source(full_name: str) -> tuple[RepoIdentity, list[ScrapedIssue]]:
        async def _identity() -> RepoIdentity:
            async with db.session() as session:
                repo = (
                    await session.execute(select(Repo).where(Repo.full_name == full_name))
                ).scalar_one_or_none()
            if repo is None or repo.gh_repo_id is None or repo.installation_id is None:
                raise RuntimeError(
                    f"repo {full_name!r} is not installed — install the GitHub App first"
                )
            return RepoIdentity(
                gh_repo_id=repo.gh_repo_id,
                full_name=repo.full_name,
                installation_id=repo.installation_id,
                default_branch=repo.default_branch,
            )

        # ``_source`` is a synchronous IssueSource but is invoked from inside
        # ``run_bootstrap``'s event loop, so ``asyncio.run`` here would raise
        # "cannot be called from a running event loop". Run the async identity
        # fetch on a worker thread, which has no running loop of its own.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            identity = pool.submit(lambda: asyncio.run(_identity())).result()
        owner, name = full_name.split("/", 1)
        token = mint_installation_token(settings, identity.installation_id, now=int(time.time()))
        with GitHubClient(RepoRef(owner, name, identity.installation_id), token) as gh:
            raw = gh.list_open_issues(label=label, limit=settings.scrape_max_jobs)
        issues = [
            ScrapedIssue(
                number=int(i["number"]),
                title=str(i.get("title") or ""),
                body=str(i.get("body") or ""),
            )
            for i in raw
        ]
        return identity, issues

    return _source


@app.command()
def main(
    reset: Annotated[bool, typer.Option(help="Wipe job tables (APP_ENV=local only)")] = False,
    scrape: Annotated[bool, typer.Option(help="Scrape open GitHub issues into jobs")] = False,
    all_issues: Annotated[bool, typer.Option(help="Ignore label; pull all open")] = False,
    max_jobs: Annotated[int | None, typer.Option(help="Override SCRAPE_MAX_JOBS")] = None,
    repos: Annotated[str | None, typer.Option(help="Comma owner/repo list")] = None,
) -> None:
    """Wipe and/or scrape for local dev. ``npm run dev`` calls this with both."""
    settings = get_settings()
    if not settings.database_url:
        console.print("[red]DATABASE_URL not configured.[/red]")
        raise typer.Exit(code=2)
    repo_list = [r.strip() for r in repos.split(",")] if repos else list(settings.scrape_repos)
    repo_list = [r for r in repo_list if r]

    db = Database.from_settings(settings)
    label = None if all_issues else (settings.scrape_label or None)
    source = _github_issue_source(db, settings, label=label) if scrape else None
    try:
        summary = asyncio.run(
            run_bootstrap(
                db,
                settings,
                reset=reset,
                scrape=scrape,
                repos=repo_list,
                issue_source=source,
                max_jobs=max_jobs,
            )
        )
    except ResetNotAllowed as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    finally:
        asyncio.run(db.dispose())

    if "reset" in summary:
        console.print(f"[green]wiped[/green] {summary['reset']}")
    if "scraped" in summary:
        console.print(f"[green]scraped[/green] {summary['scraped']}")


if __name__ == "__main__":  # pragma: no cover
    app()
