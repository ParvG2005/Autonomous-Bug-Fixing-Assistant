"""Secret redaction for logs and trace payloads (SECURITY.md C4).

Defence-in-depth on top of :class:`~app.vcs.auth.InstallationToken` (which already
redacts its own ``repr``/``str``): a structlog processor that scrubs secret-shaped
substrings out of *every* event before it is rendered, plus a value-level scrub for
keys whose name marks them sensitive. Nothing here mints or reads secrets — it only
guarantees that if one ever reaches a log/trace event, it is replaced before egress.

The same :func:`scrub` is reused by the red-team suite to assert a full run's trace
carries no token pattern.
"""

from __future__ import annotations

import re
from collections.abc import MutableMapping
from typing import Any

REDACTED = "***redacted***"

# Secret-shaped substrings. Targeted (not entropy-guessing) to avoid mangling
# ordinary text: GitHub token families, GitHub fine-grained PATs, JWTs (the App
# JWT we sign), and inline ``Authorization``/``Bearer``/``token=`` header values.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # GitHub token families: ghp_/gho_/ghu_/ghs_/ghr_ + 36+ base62 chars.
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    # GitHub fine-grained personal access tokens.
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    # JSON Web Tokens (header.payload.signature) — the signed App JWT.
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    # Inline auth headers / token assignments: `Authorization: token <x>`,
    # `Bearer <x>`, `token=<x>`. Capture the scheme/key, redact the value.
    re.compile(
        r"(?i)\b(authorization|bearer|token|api[_-]?key|secret|password)\b"
        r"(\s*[:=]\s*|\s+)(?P<scheme>token\s+|bearer\s+)?\S+"
    ),
)

# Mapping-key names whose entire value is redacted regardless of shape.
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "token",
        "access_token",
        "installation_token",
        "api_key",
        "apikey",
        "secret",
        "client_secret",
        "password",
        "private_key",
        "github_token",
        "anthropic_api_key",
    }
)


def _redact_match(match: re.Match[str]) -> str:
    """Keep a leading scheme/key marker readable; redact only the secret value."""
    groups = match.groupdict()
    if "scheme" in groups:  # the header/assignment pattern
        key, sep = match.group(1), match.group(2)
        scheme = groups.get("scheme") or ""
        return f"{key}{sep}{scheme}{REDACTED}"
    return REDACTED


def scrub(text: str) -> str:
    """Return ``text`` with every secret-shaped substring replaced by ``REDACTED``."""
    for pattern in _PATTERNS:
        text = pattern.sub(_redact_match, text)
    return text


def _scrub_value(key: str, value: Any) -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return REDACTED
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {k: _scrub_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub_value(key, v) for v in value)
    return value


def redact_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    """structlog processor: scrub secrets from every key/value in the event.

    Sensitive-named keys have their whole value redacted; all other string values
    are pattern-scrubbed. Runs last in the chain, just before rendering.
    """
    return {k: _scrub_value(str(k), v) for k, v in event_dict.items()}
