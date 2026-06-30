"""Anthropic client factory.

Isolates the only place that constructs a real Anthropic client so the loop can
stay client-agnostic (it takes a ``create_message`` callable). The API key comes
from settings (``ANTHROPIC_API_KEY``); it is never logged or placed in model
context.
"""

from __future__ import annotations

from app.agent.loop import CreateMessage
from app.core.settings import Settings, get_settings


class MissingAPIKey(RuntimeError):
    """Raised when no Anthropic API key is configured."""


def make_create_message(settings: Settings | None = None) -> CreateMessage:
    """Return ``messages.create`` bound to a configured Anthropic client."""
    import anthropic

    settings = settings or get_settings()
    if settings.anthropic_api_key is None:
        raise MissingAPIKey(
            "ANTHROPIC_API_KEY is not set; the agent loop needs an Anthropic API key"
        )
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    return client.messages.create
