"""Config, settings, secret handling, tool allowlists, security primitives.

Trusted and sensitive. Everything that holds a secret depends on this package;
nothing in the execution plane may import it.
"""

from app.core.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
