"""GitHub webhook endpoint (Phase 6).

The single rule: an ``issues`` event with ``action == "labeled"`` whose label is
the configured trigger (default ``autofix``) enqueues a job. Every delivery is
HMAC-verified against the webhook secret before its body is trusted. All other
events and actions are acknowledged and ignored.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, settings_dep
from app.api.security import EVENT_HEADER, SIGNATURE_HEADER, verify_signature
from app.core.settings import Settings
from app.db.jobs import IssueRef, ingest_labeled_issue
from app.telemetry.logging import get_logger

router = APIRouter(tags=["webhooks"])
log = get_logger("api.webhooks")


def _parse_issue_event(payload: dict[str, Any], label: str) -> IssueRef | None:
    """Extract an :class:`IssueRef` if this is a trigger-label event, else ``None``."""
    if payload.get("action") != "labeled":
        return None
    if (payload.get("label") or {}).get("name") != label:
        return None

    repo = payload.get("repository") or {}
    issue = payload.get("issue") or {}
    installation = payload.get("installation") or {}
    if not repo.get("id") or not issue.get("number") or not installation.get("id"):
        return None

    return IssueRef(
        gh_repo_id=int(repo["id"]),
        full_name=str(repo.get("full_name", "")),
        installation_id=int(installation["id"]),
        gh_issue_number=int(issue["number"]),
        issue_title=str(issue.get("title") or ""),
        issue_body=str(issue.get("body") or ""),
        default_branch=str(repo.get("default_branch") or "main"),
        language=repo.get("language"),
    )


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    settings: Settings = Depends(settings_dep),
    session: AsyncSession = Depends(get_session),
    x_github_event: str | None = Header(default=None, alias=EVENT_HEADER),
    x_hub_signature_256: str | None = Header(default=None, alias=SIGNATURE_HEADER),
) -> dict[str, Any]:
    """Verify, then enqueue a job for ``issues.labeled`` deliveries."""
    secret = settings.github_webhook_secret
    if secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook secret not configured")

    body = await request.body()
    if not verify_signature(secret.get_secret_value(), body, x_hub_signature_256):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid signature")

    if x_github_event != "issues":
        return {"status": "ignored", "reason": f"event {x_github_event!r} not handled"}

    payload = await request.json()
    ref = _parse_issue_event(payload, settings.autofix_label)
    if ref is None:
        return {"status": "ignored", "reason": "not a trigger-label issue event"}

    result = await ingest_labeled_issue(session, ref)
    log.info(
        "webhook_job",
        job_id=str(result.job.id),
        created=result.created,
        repo=ref.full_name,
        issue=ref.gh_issue_number,
    )
    return {
        "status": "queued" if result.created else "exists",
        "job_id": str(result.job.id),
        "created": result.created,
    }
