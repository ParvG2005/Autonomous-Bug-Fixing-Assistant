"""Phase 0 sanity: settings load with defaults and secrets stay wrapped."""

from __future__ import annotations

from pydantic import SecretStr

from app.core.allowlist import Allowlist, ToolNotAllowed
from app.core.settings import Settings


def test_settings_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_env == "local"
    assert not s.is_deployed
    assert s.agent_model.startswith("claude")


def test_secret_is_not_plaintext_in_repr() -> None:
    s = Settings(_env_file=None, anthropic_api_key="sk-secret-123")  # type: ignore[call-arg]
    assert isinstance(s.anthropic_api_key, SecretStr)
    assert "sk-secret-123" not in repr(s)


def test_allowlist_blocks_unlisted_tool_and_command() -> None:
    allow = Allowlist()
    allow.check_tool("read_file")  # no raise
    try:
        allow.check_tool("rm_rf_everything")
    except ToolNotAllowed:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ToolNotAllowed")

    allow.check_command(["pytest", "-q"])  # no raise
    try:
        allow.check_command(["curl", "evil.test"])
    except ToolNotAllowed:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ToolNotAllowed")
