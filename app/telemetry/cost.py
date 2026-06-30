"""Cost accounting — token spend converted to USD via a per-model price table.

Prices are list rates in US dollars per **million** tokens, split by input and
output. The table is keyed by the base model id; a model id carrying a context
suffix (e.g. ``claude-opus-4-8[1m]``) resolves to its base price. An unknown
model costs ``0.0`` (and the caller still has the raw token counts) rather than
guessing a rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelPrice:
    """List price for one model, in USD per million tokens."""

    input_per_mtok: float
    output_per_mtok: float


# Public Anthropic list prices ($/Mtok). Keep base ids here; suffixes resolve below.
MODEL_PRICING: dict[str, ModelPrice] = {
    "claude-opus-4-8": ModelPrice(15.0, 75.0),
    "claude-sonnet-4-6": ModelPrice(3.0, 15.0),
    "claude-haiku-4-5-20251001": ModelPrice(1.0, 5.0),
}

_MTOK = 1_000_000.0


def _base_model(model: str) -> str:
    """Strip a context-window suffix like ``[1m]`` to the base id."""
    return model.split("[", 1)[0]


def price_for(model: str) -> ModelPrice | None:
    """Return the price for ``model`` (resolving any suffix), or ``None``."""
    return MODEL_PRICING.get(model) or MODEL_PRICING.get(_base_model(model))


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost of ``input_tokens`` + ``output_tokens`` at ``model``'s rate.

    Unknown models cost ``0.0``. Rounded to 6 decimals (sub-cent precision).
    """
    price = price_for(model)
    if price is None:
        return 0.0
    cost = (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / _MTOK
    return round(cost, 6)


def cost_breakdown(model: str, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    """Itemized cost record suitable for storing on ``job.cost``."""
    price = price_for(model)
    in_cost = round(input_tokens * price.input_per_mtok / _MTOK, 6) if price else 0.0
    out_cost = round(output_tokens * price.output_per_mtok / _MTOK, 6) if price else 0.0
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost_usd": in_cost,
        "output_cost_usd": out_cost,
        "cost_usd": round(in_cost + out_cost, 6),
    }
