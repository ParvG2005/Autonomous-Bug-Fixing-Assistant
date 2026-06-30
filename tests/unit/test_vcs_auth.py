"""C4 token handling: App JWT signing, token-exchange, and redaction."""

from __future__ import annotations

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from app.core.settings import Settings
from app.vcs.auth import (
    GitHubAuthError,
    InstallationToken,
    build_app_jwt,
    mint_installation_token,
)

_NOW = 1_750_000_000


def _rsa_pem() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_pem, public_pem


def test_build_app_jwt_roundtrips() -> None:
    private_pem, public_pem = _rsa_pem()
    token = build_app_jwt("12345", private_pem, now=_NOW)
    claims = jwt.decode(
        token, public_pem, algorithms=["RS256"], options={"verify_exp": False}
    )
    assert claims["iss"] == "12345"
    assert claims["iat"] == _NOW - 60  # backdated for skew
    assert claims["exp"] > _NOW


def test_installation_token_redacts_value() -> None:
    tok = InstallationToken(value="ghs_supersecret", expires_at="2026-06-30T01:00:00Z")
    assert "ghs_supersecret" not in repr(tok)
    assert "ghs_supersecret" not in str(tok)
    assert "redacted" in repr(tok)
    assert tok.value == "ghs_supersecret"  # still usable


def test_mint_installation_token_posts_jwt_and_returns_token() -> None:
    private_pem, _ = _rsa_pem()
    settings = Settings(github_app_id="42", github_app_private_key=SecretStr(private_pem))
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        return httpx.Response(
            201, json={"token": "ghs_minted", "expires_at": "2026-06-30T01:00:00Z"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    tok = mint_installation_token(settings, 999, now=_NOW, http=client)

    assert tok.value == "ghs_minted"
    assert captured["url"].endswith("/app/installations/999/access_tokens")  # type: ignore[union-attr]
    assert captured["auth"].startswith("Bearer ")  # type: ignore[union-attr]


def test_mint_requires_configured_credentials() -> None:
    with pytest.raises(GitHubAuthError, match="not configured"):
        mint_installation_token(Settings(), 1, now=_NOW)


def test_mint_raises_on_non_201_without_leaking_body() -> None:
    private_pem, _ = _rsa_pem()
    settings = Settings(github_app_id="42", github_app_private_key=SecretStr(private_pem))
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"jwt": "leak"}))
    )
    with pytest.raises(GitHubAuthError) as exc:
        mint_installation_token(settings, 7, now=_NOW, http=client)
    assert "leak" not in str(exc.value)
    assert "403" in str(exc.value)
