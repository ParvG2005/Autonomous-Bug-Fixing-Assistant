"""HMAC webhook signature verification (Phase 6)."""

from __future__ import annotations

from app.api.security import compute_signature, verify_signature

SECRET = "s3cret"
BODY = b'{"action":"labeled"}'


def test_compute_signature_is_deterministic_and_prefixed() -> None:
    sig = compute_signature(SECRET, BODY)
    assert sig.startswith("sha256=")
    assert sig == compute_signature(SECRET, BODY)


def test_verify_accepts_matching_signature() -> None:
    assert verify_signature(SECRET, BODY, compute_signature(SECRET, BODY)) is True


def test_verify_rejects_wrong_secret() -> None:
    assert verify_signature("other", BODY, compute_signature(SECRET, BODY)) is False


def test_verify_rejects_tampered_body() -> None:
    sig = compute_signature(SECRET, BODY)
    assert verify_signature(SECRET, BODY + b"x", sig) is False


def test_verify_rejects_missing_or_malformed_header() -> None:
    assert verify_signature(SECRET, BODY, None) is False
    assert verify_signature(SECRET, BODY, "garbage") is False
