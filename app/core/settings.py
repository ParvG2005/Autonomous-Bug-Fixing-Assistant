"""Application settings loaded from environment / .env.

Secrets live here and nowhere else. Pydantic-settings reads ``.env`` for local
dev; in CI/prod the values come from the environment / secrets manager.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration. Construct via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["local", "ci", "prod"] = "local"
    log_level: str = "INFO"

    workspace_root: Path = Field(default=Path("./workspaces"))

    # --- Anthropic (Phase 3+) ---
    anthropic_api_key: SecretStr | None = None
    agent_model: str = "claude-opus-4-8"
    agent_localizer_model: str = "claude-haiku-4-5-20251001"

    # --- Data stores (later phases) ---
    database_url: str | None = None
    db_echo: bool = False
    redis_url: str | None = None

    # --- API / webhook (Phase 6+) ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    autofix_label: str = "autofix"  # the issue label that triggers a job
    #: Browser origins allowed to call the API (the dashboard dev server). In
    #: production the built assets are served same-origin, so this is dev-only.
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # --- Dev bootstrap / scrape (Phase 14, dev-only) ---
    #: Let ``npm run dev`` run the wipe+scrape bootstrap on startup.
    scrape_on_start: bool = False
    #: Issue label to pull (empty / ``--all-issues`` = every open issue).
    scrape_label: str = "autofix"
    #: Safety cap on how many jobs a single scrape enqueues.
    scrape_max_jobs: int = 10
    #: Installed repos to scrape, ``owner/repo`` each.
    scrape_repos: list[str] = Field(default_factory=list)

    # --- GitHub App (Phase 5+) ---
    github_app_id: str | None = None
    github_app_private_key: SecretStr | None = None
    github_webhook_secret: SecretStr | None = None

    # --- Langfuse (Phase 10+) ---
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str | None = None

    @property
    def is_deployed(self) -> bool:
        """True in any non-local environment; gates the local sandbox fallback."""
        return self.app_env in ("ci", "prod")


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process-wide settings instance."""
    return Settings()
