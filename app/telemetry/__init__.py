"""structlog setup, Langfuse trace emission, cost accounting, metrics.

See ARCHITECTURE.md §9. Phase 10 fills this in: structured logging (with the
Phase-9 redaction filter), a replayable agent trace mirrored to Langfuse, USD
cost accounting per job, and the fleet metrics (resolve/regression/time/cost).
"""

from app.telemetry.cost import MODEL_PRICING, cost_breakdown, cost_usd
from app.telemetry.logging import configure_logging, get_logger
from app.telemetry.metrics import JobOutcome, Metrics, compute_metrics
from app.telemetry.tracing import (
    NullTracer,
    Tracer,
    build_trace,
    get_tracer,
)

__all__ = [
    "MODEL_PRICING",
    "JobOutcome",
    "Metrics",
    "NullTracer",
    "Tracer",
    "build_trace",
    "compute_metrics",
    "configure_logging",
    "cost_breakdown",
    "cost_usd",
    "get_logger",
    "get_tracer",
]
