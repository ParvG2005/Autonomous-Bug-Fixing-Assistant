"""structlog setup, Langfuse trace emission, cost accounting, metrics.

See ARCHITECTURE.md §9. Phase 10 fills this in; the scaffold provides logger
configuration so every package can emit structured logs from day one.
"""

from app.telemetry.logging import configure_logging, get_logger

__all__ = ["configure_logging", "get_logger"]
