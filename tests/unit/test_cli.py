"""CLI smoke tests via Typer's runner (no network)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from app.index.cli import app

runner = CliRunner()


def test_where_command_reports_definition(workspace: Path) -> None:
    result = runner.invoke(app, ["where", str(workspace), "Greeter"])
    assert result.exit_code == 0
    assert "Defined" in result.stdout
    assert "Greeter" in result.stdout


def test_where_unknown_symbol_exits_nonzero(workspace: Path) -> None:
    result = runner.invoke(app, ["where", str(workspace), "nope_nope"])
    assert result.exit_code == 1


def test_search_command(workspace: Path) -> None:
    result = runner.invoke(app, ["search", str(workspace), "greet", "--word"])
    assert result.exit_code == 0
    assert "match(es)" in result.stdout
