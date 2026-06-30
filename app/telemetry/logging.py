"""Structured logging configuration.

A thin structlog wrapper so every package shares one logging setup with a
per-job correlation id. Phase 10 extends this with Langfuse + cost accounting.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog

from app.telemetry.redaction import redact_processor


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging for the process (idempotent enough)."""
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            # C4: scrub secrets from every event right before it is rendered.
            redact_processor,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None, **initial: Any) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger, optionally seeded with context."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    if initial:
        logger = logger.bind(**initial)
    return logger
