"""Offline tests for the bugfix-eval CLI — list + the spend/key gates.

The CLI's *real* run path costs tokens, so these tests cover only the surface that
must work offline: listing a suite and refusing to spend without --confirm / a key.
"""

from __future__ import annotations

from types import SimpleNamespace

import eval.cli as cli
import pytest
from typer.testing import CliRunner

runner = CliRunner()


def _settings(key: str | None) -> SimpleNamespace:
    return SimpleNamespace(anthropic_api_key=key, agent_model="claude-opus-4-8")


def test_list_prints_custom_cases() -> None:
    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code == 0
    assert "01-titleize" in result.stdout


def test_run_without_key_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(None))
    result = runner.invoke(cli.app, ["run", "--confirm"])
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY" in result.stdout


def test_run_without_confirm_refuses_to_spend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: _settings("sk-test"))
    result = runner.invoke(cli.app, ["run"])
    assert result.exit_code == 2
    assert "--confirm" in result.stdout


def test_run_swebench_without_jsonl_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: _settings("sk-test"))
    result = runner.invoke(cli.app, ["run", "--suite", "swebench-lite", "--confirm"])
    assert result.exit_code == 2
    assert "--jsonl" in result.stdout
