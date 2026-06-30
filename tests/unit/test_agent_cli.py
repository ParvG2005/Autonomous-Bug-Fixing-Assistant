"""Offline smoke tests for the ``bugfix-agent`` CLI (no network)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import app.agent.cli as cli_mod
from app.agent.cli import app
from app.agent.client import MissingAPIKey

runner = CliRunner()


def test_solve_requires_an_issue(tmp_path: Path) -> None:
    result = runner.invoke(app, ["solve", str(tmp_path)])
    assert result.exit_code == 2
    assert "issue" in result.stdout.lower()


def test_solve_exits_when_client_unavailable(failing_project: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # When no API key is configured the client factory raises; the CLI exits 2.
    def _boom(_settings: object) -> None:
        raise MissingAPIKey("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(cli_mod, "make_create_message", _boom)
    result = runner.invoke(app, ["solve", str(failing_project), "--issue", "divide crashes"])
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY" in result.stdout
