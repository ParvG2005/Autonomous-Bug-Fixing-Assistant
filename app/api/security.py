"""GitHub webhook signature verification (Phase 6 / SECURITY.md).

GitHub signs each delivery with HMAC-SHA256 over the raw request body, keyed by
the webhook secret, in the ``X-Hub-Signature-256: sha256=<hex>`` header. We
recompute it and compare in constant time. The secret never leaves this process
and is never logged.
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "X-Hub-Signature-256"
EVENT_HEADER = "X-GitHub-Event"
DELIVERY_HEADER = "X-GitHub-Delivery"


def compute_signature(secret: str, body: bytes) -> str:
    """Return the ``sha256=<hex>`` signature GitHub would send for ``body``."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body: bytes, header_value: str | None) -> bool:
    """Constant-time check that ``header_value`` matches the HMAC of ``body``.

    Returns ``False`` (never raises) on a missing or malformed header so callers
    can map every failure to a single 401.
    """
    if not header_value:
        return False
    expected = compute_signature(secret, body)
    return hmac.compare_digest(expected, header_value)
