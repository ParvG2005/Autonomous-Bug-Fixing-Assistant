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
    redis_url: str | None = None

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
