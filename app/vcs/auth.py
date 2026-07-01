"""GitHub App authentication (Phase 5 / SECURITY.md C4).

A GitHub App proves identity with a short-lived RS256 JWT signed by its private
key, then exchanges that JWT for an **installation access token** scoped to one
install. The installation token is what mints branches/commits/PRs.

Both secrets are handled here and only here. The token is wrapped in
:class:`InstallationToken`, whose ``repr``/``str`` redact the value so it never
leaks into logs, tracebacks, or Langfuse payloads. Callers use it inside the
publish path and discard it; nothing persists it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt

from app.core.settings import Settings

GITHUB_API = "https://api.github.com"
_JWT_TTL_S = 540  # GitHub caps app-JWT lifetime at 10 min; stay under it.


class GitHubAuthError(Exception):
    """Raised when App auth or token exchange fails."""


@dataclass(frozen=True)
class InstallationToken:
    """A short-lived installation token, held in memory only.

    ``expires_at`` is GitHub's ISO-8601 expiry. The token value is excluded from
    ``repr``/``str`` (``field(repr=False)`` plus an explicit override) so logging
    the object can never disclose it.
    """

    value: str = field(repr=False)
    expires_at: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"<InstallationToken expires_at={self.expires_at} value=***redacted***>"

    __repr__ = __str__


def build_app_jwt(app_id: str, private_key: str, *, now: int) -> str:
    """Sign the App JWT (RS256). ``now`` is a Unix timestamp supplied by the caller.

    ``iat`` is backdated 60s to tolerate clock skew, per GitHub's guidance.
    """
    payload = {"iat": now - 60, "exp": now + _JWT_TTL_S, "iss": app_id}
    try:
        return jwt.encode(payload, private_key, algorithm="RS256")
    except Exception as exc:
        raise GitHubAuthError(f"failed to sign App JWT: {exc}") from exc


def mint_installation_token(
    settings: Settings,
    installation_id: int,
    *,
    now: int,
    http: httpx.Client | None = None,
) -> InstallationToken:
    """Exchange the App JWT for an installation token scoped to ``installation_id``.

    ``now`` (Unix time) is injected so the JWT is deterministic and testable. The
    token is returned in memory; the caller is responsible for not persisting it.
    """
    if settings.github_app_id is None or settings.github_app_private_key is None:
        raise GitHubAuthError("GitHub App credentials are not configured")

    app_jwt = build_app_jwt(
        settings.github_app_id,
        settings.github_app_private_key.get_secret_value(),
        now=now,
    )
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{GITHUB_API}/app/installations/{installation_id}/access_tokens"

    client = http or httpx.Client(timeout=30.0)
    try:
        resp = client.post(url, headers=headers)
    finally:
        if http is None:
            client.close()

    if resp.status_code != 201:
        # Never echo the response body verbatim — it may contain the JWT we sent.
        raise GitHubAuthError(
            f"token exchange failed for installation {installation_id}: HTTP {resp.status_code}"
        )
    data: dict[str, Any] = resp.json()
    return InstallationToken(value=data["token"], expires_at=data.get("expires_at", ""))


def resolve_repo_installation(
    settings: Settings,
    full_name: str,
    *,
    now: int,
    http: httpx.Client | None = None,
) -> tuple[int, int]:
    """Resolve ``(gh_repo_id, installation_id)`` for ``full_name`` via the GitHub App.

    Calls ``GET /repos/{full_name}/installation`` (which accepts the App JWT) for
    the installation id, mints an installation access token, then calls
    ``GET /repos/{full_name}`` **with that token** for the repo id. The plain repo
    endpoint rejects an App JWT (HTTP 401), so the token step is required. Raises
    :class:`GitHubAuthError` if credentials are unconfigured or a call does not
    return 200; response bodies are never echoed (they may contain the JWT).
    """
    if settings.github_app_id is None or settings.github_app_private_key is None:
        raise GitHubAuthError("GitHub App credentials are not configured")

    app_jwt = build_app_jwt(
        settings.github_app_id,
        settings.github_app_private_key.get_secret_value(),
        now=now,
    )
    jwt_headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    client = http or httpx.Client(timeout=30.0)
    try:
        # The installation endpoint accepts the App JWT and yields the id we need
        # to mint a token. Resolve it first.
        install_resp = client.get(
            f"{GITHUB_API}/repos/{full_name}/installation", headers=jwt_headers
        )
        if install_resp.status_code != 200:
            raise GitHubAuthError(
                f"installation lookup failed for {full_name}: HTTP {install_resp.status_code}"
            )
        installation_id = install_resp.json()["id"]

        # The plain repo lookup rejects an App JWT (401); it needs an installation
        # access token scoped to this repo.
        token = mint_installation_token(settings, installation_id, now=now, http=client)
        repo_headers = {
            "Authorization": f"token {token.value}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        repo_resp = client.get(f"{GITHUB_API}/repos/{full_name}", headers=repo_headers)
        if repo_resp.status_code != 200:
            raise GitHubAuthError(
                f"repo lookup failed for {full_name}: HTTP {repo_resp.status_code}"
            )
        gh_repo_id = repo_resp.json()["id"]
    finally:
        if http is None:
            client.close()

    return (gh_repo_id, installation_id)


# A minter is injectable so the publish path can be driven offline in tests.
TokenMinter = Callable[[int], InstallationToken]


def settings_token_minter(settings: Settings, *, now: int) -> TokenMinter:
    """Bind a real :func:`mint_installation_token` to ``settings`` and a clock."""

    def _mint(installation_id: int) -> InstallationToken:
        return mint_installation_token(settings, installation_id, now=now)

    return _mint
