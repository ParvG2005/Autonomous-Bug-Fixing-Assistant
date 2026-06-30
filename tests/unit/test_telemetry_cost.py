"""Cost accounting: token spend -> USD via a per-model price table."""

from __future__ import annotations

import pytest

from app.telemetry.cost import MODEL_PRICING, cost_breakdown, cost_usd


def test_opus_cost_uses_input_and_output_rates() -> None:
    # opus 4.8: $15 / Mtok in, $75 / Mtok out.
    # 1M in + 1M out = 15 + 75 = 90.0
    assert cost_usd("claude-opus-4-8", 1_000_000, 1_000_000) == pytest.approx(90.0)


def test_haiku_is_cheaper_than_opus_for_same_tokens() -> None:
    assert cost_usd("claude-haiku-4-5-20251001", 500_000, 500_000) < cost_usd(
        "claude-opus-4-8", 500_000, 500_000
    )


def test_unknown_model_costs_zero() -> None:
    assert cost_usd("no-such-model", 1_000_000, 1_000_000) == 0.0


def test_model_id_with_1m_suffix_falls_back_to_base_price() -> None:
    # The loop may run "claude-opus-4-8[1m]"; pricing should resolve the base id.
    assert cost_usd("claude-opus-4-8[1m]", 1_000_000, 0) == pytest.approx(15.0)


def test_breakdown_carries_tokens_costs_and_total() -> None:
    bd = cost_breakdown("claude-opus-4-8", 1_000_000, 2_000_000)
    assert bd["model"] == "claude-opus-4-8"
    assert bd["input_tokens"] == 1_000_000
    assert bd["output_tokens"] == 2_000_000
    assert bd["input_cost_usd"] == pytest.approx(15.0)
    assert bd["output_cost_usd"] == pytest.approx(150.0)
    assert bd["cost_usd"] == pytest.approx(165.0)


def test_pricing_table_covers_configured_models() -> None:
    for model in ("claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"):
        assert model in MODEL_PRICING
