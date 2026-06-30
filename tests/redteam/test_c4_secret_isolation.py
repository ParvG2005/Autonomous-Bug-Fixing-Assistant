"""C4 — Secret isolation; §5 category 5 (secret-exfiltration probes).

Tokens are short-lived, in-memory, and must never reach logs, tracebacks, trace
payloads, or model context. Proven by: the token wrapper redacts its own repr;
the structlog redaction filter scrubs secret-shaped substrings *and* sensitive
keys end to end; error messages on the auth/REST path never echo the token; and
the model context assembled for a job carries no system secret.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.agent.models import AgentBudget
from app.agent.solve import solve_issue
from app.sandbox import LocalSandbox, ResourceLimits
from app.telemetry.logging import configure_logging, get_logger
from app.telemetry.redaction import REDACTED, redact_processor, scrub
from app.vcs.auth import GitHubAuthError, InstallationToken

from .conftest import FAKE_GH_TOKEN, FAKE_JWT, FAKE_PAT, INJECTION_ISSUES
from .test_c3_prompt_injection import _CompliantClient

pytestmark = pytest.mark.redteam


# --- the token wrapper never discloses its value ------------------------------


def test_installation_token_repr_is_redacted() -> None:
    tok = InstallationToken(value=FAKE_GH_TOKEN, expires_at="2026-06-30T00:00:00Z")
    assert FAKE_GH_TOKEN not in repr(tok)
    assert FAKE_GH_TOKEN not in str(tok)
    assert "redacted" in repr(tok)


# --- scrub() catches every token family we handle -----------------------------


@pytest.mark.parametrize("secret", [FAKE_GH_TOKEN, FAKE_PAT, FAKE_JWT])
def test_scrub_removes_token_shapes(secret: str) -> None:
    text = f"the token is {secret} ok"
    out = scrub(text)
    assert secret not in out
    assert REDACTED in out


def test_scrub_redacts_inline_auth_header() -> None:
    out = scrub("Authorization: token abc123def456 trailing")
    assert "abc123def456" not in out
    assert "Authorization" in out  # key kept readable, value gone


def test_scrub_leaves_ordinary_text_untouched() -> None:
    text = "fixed the divide-by-zero in calc.py at line 5"
    assert scrub(text) == text


# --- the structlog processor scrubs keys and embedded secrets -----------------


def test_redact_processor_scrubs_sensitive_key() -> None:
    out = redact_processor(None, "info", {"event": "minted", "token": FAKE_GH_TOKEN})
    assert out["token"] == REDACTED


def test_redact_processor_scrubs_embedded_secret() -> None:
    out = redact_processor(None, "info", {"event": f"sending {FAKE_JWT} now"})
    assert FAKE_JWT not in out["event"]


def test_redact_processor_recurses_into_nested_payloads() -> None:
    out = redact_processor(
        None, "info", {"event": "x", "headers": {"authorization": FAKE_GH_TOKEN}}
    )
    assert out["headers"]["authorization"] == REDACTED


def test_logging_pipeline_scrubs_token_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    get_logger("redteam").info("token_event", token=FAKE_GH_TOKEN, note=f"hdr {FAKE_JWT}")
    captured = capsys.readouterr()
    blob = captured.out + captured.err
    assert FAKE_GH_TOKEN not in blob
    assert FAKE_JWT not in blob


# --- the auth/REST path never echoes a token in errors ------------------------


def test_auth_error_message_has_no_token() -> None:
    err = GitHubAuthError("token exchange failed for installation 5: HTTP 403")
    assert FAKE_GH_TOKEN not in str(err)


# --- model context assembled for a job carries no system secret ---------------


def test_model_context_contains_no_secret(failing_project: Path) -> None:
    """Run the solver; the full prompt/tool stream sent to the model has no secret."""
    client = _CompliantClient()
    solve_issue(
        failing_project,
        INJECTION_ISSUES[1],  # tells the agent to print $GITHUB_TOKEN
        client.create,
        model="claude-opus-4-8",
        sandbox=LocalSandbox(),
        budget=AgentBudget(max_iterations=4, deadline_s=60.0),
        limits=ResourceLimits(timeout_s=30.0),
    )
    everything = json.dumps([_jsonable(c) for c in client.calls])
    for secret in (FAKE_GH_TOKEN, FAKE_PAT, FAKE_JWT):
        assert secret not in everything
    # No GitHub token prefix of any family appears in the assembled context.
    assert "ghs_" not in everything and "github_pat_" not in everything


def _jsonable(obj: Any) -> Any:
    """Best-effort stringify of create() kwargs (messages may hold dataclasses)."""
    try:
        return json.loads(json.dumps(obj, default=str))
    except TypeError:  # pragma: no cover - defensive
        return str(obj)
