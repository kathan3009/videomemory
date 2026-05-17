"""videomemory CLI.

  videomemory setup            # check deps + pre-pull models + print install snippets
  videomemory add <url>        # ingest a URL or path
  videomemory skip <url> "q"   # find the timestamp answering q
  videomemory search "q"       # cross-video search
  videomemory understand <url> # summary + chapters
  videomemory list             # list library
  videomemory history <path>   # import Google Takeout watch history
  videomemory export <path>    # export library bundle
  videomemory import <path>    # import library bundle (Watch Club)
  videomemory mcp serve        # stdio MCP server
  videomemory serve            # HTTP server (demo + REST + HTTP MCP)
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from videomemory import __version__
from videomemory.config import data_dir
from videomemory.ingest import fmt_time

app = typer.Typer(
    name="videomemory",
    help="The video understanding layer for Claude Code & Codex.",
    no_args_is_help=False,
    add_completion=False,
    invoke_without_command=True,
)
mcp_app = typer.Typer(help="MCP server commands.")
app.add_typer(mcp_app, name="mcp")

console = Console()


@app.callback()
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
    data_dir_opt: str | None = typer.Option(
        None, "--data-dir", help="Override the library directory (also: VIDEOMEMORY_DATA_DIR).",
    ),
) -> None:
    if data_dir_opt:
        os.environ["VIDEOMEMORY_DATA_DIR"] = data_dir_opt
    if version:
        console.print(f"videomemory {__version__}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


@app.command()
def setup() -> None:
    """Check dependencies, pre-pull models, print install snippets."""
    from videomemory.deps import check, install_snippets, prepull_models

    console.print(f"[bold]videomemory[/bold] {__version__}  ·  data_dir = {data_dir()}\n")

    rows = check()
    t = Table(show_header=True, header_style="bold")
    t.add_column("dependency"); t.add_column("status"); t.add_column("version"); t.add_column("fix")
    for r in rows:
        t.add_row(r.name, "[green]✓[/green]" if r.ok else "[red]✗[/red]", r.version or "-", r.fix or "-")
    console.print(t)

    missing = [r for r in rows if not r.ok and r.fix]
    if missing:
        console.print("\n[yellow]Missing tools.[/yellow] Run the printed fix commands and try again.")
        raise typer.Exit(1)

    console.print("\n[bold]Pre-pulling models...[/bold] (one-time, ~1 GB)")
    prepull_models()
    console.print("Done.\n")

    snips = install_snippets()
    console.print("[bold]Install in Claude Code (local):[/bold]")
    console.print(snips["claude_code_local"])
    console.print("\n[bold]Install in Claude Code (remote, hosted):[/bold]")
    console.print(snips["claude_code_remote"])
    console.print("\n[bold]Codex config (local):[/bold]")
    console.print(snips["codex_local_json"])


@app.command()
def add(source: str = typer.Argument(...)) -> None:
    """Ingest a URL or local file into the library."""
    from videomemory.ingest import ingest

    v = asyncio.run(ingest(source))
    console.print(f"[green]added[/green] {v.video_id}  {v.title or ''}  ({v.duration:.0f}s)")


@app.command()
def skip(
    url: str = typer.Argument(...),
    question: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Find the exact moment in `url` that answers `question`."""
    from videomemory.search import skip as one_skip

    h = asyncio.run(one_skip(url, question))
    if json_out:
        console.print_json(data=h.model_dump(mode="json") if h else None)
        return
    if not h:
        console.print("[red]no match[/red]"); raise typer.Exit(1)
    console.print(f"\n[bold green]{h.timestamp_human}[/bold green]  {h.deep_link}")
    console.print(f"[dim]{h.title or h.video_id}  · score={h.score:.3f}[/dim]\n")
    console.print(h.transcript_excerpt)
    if h.frame_uri:
        console.print(f"\n[dim]frame: {h.frame_uri}[/dim]")


@app.command(name="search")
def cmd_search(
    query: str = typer.Argument(...),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Search across every video in your library."""
    from videomemory.search import search as cross_search

    hits = cross_search(query, top_k=top_k)
    if json_out:
        console.print_json(data=[h.model_dump(mode="json") for h in hits]); return
    if not hits:
        console.print("[yellow]no hits[/yellow]"); return
    t = Table(show_header=True, header_style="bold")
    t.add_column("time"); t.add_column("score", justify="right"); t.add_column("video"); t.add_column("snippet")
    for h in hits:
        t.add_row(h.timestamp_human, f"{h.score:.3f}", h.title or h.video_id, h.transcript_excerpt[:60] + ("…" if len(h.transcript_excerpt) > 60 else ""))
    console.print(t)
    for h in hits:
        console.print(f"  → {h.deep_link}")


@app.command()
def understand(url: str = typer.Argument(...)) -> None:
    """Watch and summarise a video."""
    from videomemory.understand import understand as one_understand

    s = asyncio.run(one_understand(url))
    console.print(f"\n[bold]{s.title or s.video_id}[/bold]  ({s.duration:.0f}s)")
    console.print(f"[dim]{s.source}[/dim]\n")
    for b in s.bullets:
        console.print(f"  • {b}")
    if s.chapters:
        console.print("\n[bold]chapters[/bold]")
        for c in s.chapters:
            console.print(f"  [green]{c.timestamp_human}[/green]  {c.deep_link}  — {c.transcript_excerpt[:80]}")


@app.command(name="list")
def list_cmd() -> None:
    """List videos in your library."""
    from videomemory.library import list_videos

    vs = list_videos()
    if not vs:
        console.print("[dim]library is empty — try: videomemory add <url>[/dim]"); return
    t = Table(show_header=True, header_style="bold")
    t.add_column("video_id"); t.add_column("title"); t.add_column("duration", justify="right"); t.add_column("added")
    for v in vs:
        t.add_row(v.video_id, v.title or "", fmt_time(v.duration), v.added_at.strftime("%Y-%m-%d"))
    console.print(t)


@app.command()
def history(
    path: Path = typer.Argument(..., help="Path to Google Takeout watch-history.json or .html"),
    limit: int = typer.Option(50, "--limit", "-n", help="Ingest at most N videos this run (resume by re-running)."),
    concurrency: int = typer.Option(2, "--concurrency"),
) -> None:
    """Import your YouTube watch history into the library."""
    from videomemory.youtube_history import import_history

    console.print(f"[bold]importing[/bold] up to {limit} videos at concurrency={concurrency}...")
    results = asyncio.run(
        import_history(path, limit=limit, concurrency=concurrency, progress=console.log)
    )
    ok = sum(1 for r in results if not isinstance(r, Exception))
    fail = sum(1 for r in results if isinstance(r, Exception))
    console.print(f"\n[bold green]ingested[/bold green] {ok}  ·  [yellow]failed[/yellow] {fail}")


@app.command(name="export")
def cmd_export(out: Path = typer.Argument(..., help="Output bundle path, e.g. ./my-library.sqlite")) -> None:
    """Export your library as a single-file bundle for the Watch Club."""
    from videomemory.library import export_bundle

    p = export_bundle(out)
    console.print(f"[green]exported[/green] {p}")


@app.command(name="import")
def cmd_import(
    bundle: Path = typer.Argument(...),
    merge: bool = typer.Option(True, "--merge/--replace"),
) -> None:
    """Import a Watch Club bundle from a friend."""
    from videomemory.library import import_bundle

    n = import_bundle(bundle, merge=merge)
    console.print(f"[green]imported[/green] {n} videos from {bundle}")


@mcp_app.command("serve")
def mcp_serve(
    data_dir_opt: str | None = typer.Option(None, "--data-dir"),
) -> None:
    """Start the stdio MCP server."""
    if data_dir_opt:
        os.environ["VIDEOMEMORY_DATA_DIR"] = data_dir_opt
    from videomemory.mcp_server import serve_stdio

    asyncio.run(serve_stdio())


@app.command(name="serve")
def http_serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
) -> None:
    """Start the HTTP server (demo + REST + HTTP MCP at /mcp)."""
    import uvicorn

    uvicorn.run("videomemory.server:app", host=host, port=port, reload=False, log_level="info")


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
