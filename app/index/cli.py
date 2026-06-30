"""``repo-brain`` CLI — a thin harness to exercise the Phase 1 tools.

    repo-brain clone  <url> <dest>          clone a repo into a workspace
    repo-brain where  <workspace> <symbol>  where is X defined / used
    repo-brain search <workspace> <pattern> lexical search
    repo-brain read   <workspace> <path>    read a file (optional --start/--end)

This is the acceptance surface for Phase 1: ``where`` answers "where is X
defined / used" on a real repo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from app.index.clone import clone_repo
from app.index.repo_brain import RepoBrain

app = typer.Typer(add_completion=False, help="Repo brain: clone, index, and query a repo.")
console = Console()


@app.command()
def clone(
    source: Annotated[str, typer.Argument(help="Git URL or local path")],
    dest: Annotated[Path, typer.Argument(help="Workspace directory to create")],
    depth: Annotated[int, typer.Option(help="Shallow clone depth (0 = full)")] = 1,
    ref: Annotated[str | None, typer.Option(help="Branch/tag to check out")] = None,
) -> None:
    """Clone a repo into a workspace."""
    path = clone_repo(source, dest, depth=depth, ref=ref)
    console.print(f"[green]cloned[/green] {source} -> {path}")


@app.command()
def where(
    workspace: Annotated[Path, typer.Argument(help="Cloned workspace directory")],
    symbol: Annotated[str, typer.Argument(help="Symbol name to locate")],
) -> None:
    """Show where SYMBOL is defined and used."""
    brain = RepoBrain(workspace)
    result = brain.find_symbol(symbol)

    if not result.found:
        console.print(f"[yellow]no definitions or usages found for[/yellow] {symbol!r}")
        raise typer.Exit(code=1)

    console.print(f"[bold]{symbol}[/bold]  ({brain.symbol_count} symbols indexed)")
    console.print(f"\n[bold cyan]Defined[/bold cyan] ({len(result.definitions)})")
    for sym in result.definitions:
        console.print(f"  {sym.kind.value:8} {sym.qualified_name:30} {sym.location}")

    console.print(f"\n[bold cyan]Used[/bold cyan] ({len(result.usages)})")
    for hit in result.usages[:50]:
        console.print(f"  {hit}")
    if len(result.usages) > 50:
        console.print(f"  ... and {len(result.usages) - 50} more")


@app.command()
def search(
    workspace: Annotated[Path, typer.Argument(help="Cloned workspace directory")],
    pattern: Annotated[str, typer.Argument(help="Regex (or literal with --fixed)")],
    word: Annotated[bool, typer.Option(help="Match whole words only")] = False,
    fixed: Annotated[bool, typer.Option(help="Treat pattern as a literal string")] = False,
) -> None:
    """Lexical search across the workspace."""
    brain = RepoBrain(workspace)
    hits = brain.search(pattern, word=word, fixed=fixed)
    for hit in hits:
        console.print(str(hit))
    console.print(f"[dim]{len(hits)} match(es)[/dim]")


@app.command()
def read(
    workspace: Annotated[Path, typer.Argument(help="Cloned workspace directory")],
    path: Annotated[str, typer.Argument(help="File path relative to the workspace")],
    start: Annotated[int, typer.Option(help="Start line (1-based)")] = 1,
    end: Annotated[int | None, typer.Option(help="End line (inclusive)")] = None,
) -> None:
    """Read a file (or a line range) from the workspace."""
    brain = RepoBrain(workspace)
    sliced = brain.read_file(path, start_line=start, end_line=end)
    console.print(f"[dim]{sliced.path}:{sliced.start_line}-{sliced.end_line}[/dim]")
    console.print(sliced.text)


if __name__ == "__main__":
    app()
