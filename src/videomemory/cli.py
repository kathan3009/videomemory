"""videomemory CLI.

  videomemory setup            # check deps + pre-pull models + print install snippets
  videomemory add <url>        # ingest a URL or path
  videomemory skip <url> "q"   # find the timestamp answering q
  videomemory frames <url>     # sample N keyframes (for visual videos)
  videomemory search "q"       # cross-video search
  videomemory understand <url> # summary + chapters
  videomemory list             # list library
  videomemory history <path>   # import Google Takeout watch history
  videomemory export <path>    # export library bundle
  videomemory import <path>    # import library bundle (Watch Club)
  videomemory mcp serve        # stdio MCP server
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

scribe_app = typer.Typer(help="Scribe — full-screen capture, OCR, daily digests.")
app.add_typer(scribe_app, name="scribe")

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
    console.print("[bold]Install in Claude Code:[/bold]")
    console.print(snips["claude_code"])
    console.print("\n[bold]Codex (or any MCP client) config:[/bold]")
    console.print(snips["codex_json"])


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


@app.command(name="frames")
def cmd_frames(
    url: str = typer.Argument(...),
    count: int = typer.Option(8, "--count", "-n", help="N evenly-spaced frames."),
    every: float | None = typer.Option(None, "--every", help="A frame every X seconds."),
    at: str | None = typer.Option(None, "--at", help="Explicit timestamps, comma-separated seconds."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Sample keyframes for visual reasoning (works on silent videos too)."""
    import asyncio as _asyncio

    from videomemory.frames import get_frames

    at_list = [float(s) for s in at.split(",")] if at else None
    frames = _asyncio.run(get_frames(url, count=count, every=every, at=at_list))
    if json_out:
        console.print_json(data=[f.model_dump(mode="json") for f in frames]); return
    if not frames:
        console.print("[yellow]no frames extracted[/yellow]"); return
    for f in frames:
        console.print(f"  [green]{f.timestamp_human}[/green]  {f.deep_link}  · {f.frame_uri}")


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


# --------------------- scribe subcommands ---------------------


@scribe_app.command("start")
def scribe_start() -> None:
    """Start the background capture daemon."""
    from videomemory.scribe import daemon as d

    pid = d.start_background()
    console.print(f"[green]scribe started[/green]  pid={pid}  log={d.log_file()}")
    console.print(
        "[dim]first run on macOS will trigger the Screen Recording permission prompt.[/dim]"
    )


@scribe_app.command("stop")
def scribe_stop() -> None:
    from videomemory.scribe import daemon as d

    ok = d.stop_background()
    if ok:
        console.print("[green]scribe stopped[/green]")
    else:
        console.print("[yellow]scribe was not running[/yellow]")


@scribe_app.command("pause")
def scribe_pause() -> None:
    from videomemory.scribe import daemon as d

    d.pause(); console.print("[yellow]paused[/yellow]")


@scribe_app.command("resume")
def scribe_resume() -> None:
    from videomemory.scribe import daemon as d

    d.resume(); console.print("[green]resumed[/green]")


@scribe_app.command("status")
def scribe_status() -> None:
    from videomemory.scribe import daemon as d
    from videomemory.scribe.store import stats as scribe_stats

    pid = d.is_running()
    s = scribe_stats()
    state = "running" if pid else "stopped"
    if d.is_paused():
        state = "paused"
    console.print(f"[bold]scribe[/bold] · {state}" + (f" (pid {pid})" if pid else ""))
    console.print(f"[dim]log:[/dim]  {d.log_file()}")
    t = Table(show_header=True, header_style="bold")
    t.add_column("metric"); t.add_column("value", justify="right")
    t.add_row("ephemeral frames",   str(s["ephemeral_frames"]))
    t.add_row("ephemeral sessions", str(s["ephemeral_sessions"]))
    t.add_row("ephemeral notes",    str(s["ephemeral_notes"]))
    t.add_row("durable days",       str(s["durable_days"]))
    t.add_row("durable lines",      str(s["durable_lines"]))
    if s["first_capture"]:
        t.add_row("first capture",  str(s["first_capture"]))
    if s["last_capture"]:
        t.add_row("last capture",   str(s["last_capture"]))
    console.print(t)


@scribe_app.command("end")
def scribe_end() -> None:
    """End the current day — compile digest, write durable markdown, purge raw frames."""
    from videomemory.scribe.digest import build_today_digest

    out = asyncio.run(build_today_digest())
    if out is None:
        console.print("[yellow]nothing captured today yet[/yellow]")
        return
    console.print(f"[green]day digest written[/green]  {out}")
    console.print("[dim]raw frames + ephemeral sessions purged[/dim]")


@scribe_app.command("digest")
def scribe_digest() -> None:
    """Same as `scribe end` — write today's digest now."""
    scribe_end()


@scribe_app.command("today")
def scribe_today() -> None:
    """Print today's digest if it exists, else compile one."""
    from datetime import date as _date

    from videomemory.scribe.digest import days_dir
    today_md = days_dir() / f"{_date.today().isoformat()}.md"
    if not today_md.exists():
        from videomemory.scribe.digest import build_today_digest
        out = asyncio.run(build_today_digest())
        if out is None:
            console.print("[yellow]no activity today[/yellow]"); return
        today_md = out
    console.print(today_md.read_text())


@scribe_app.command("search")
def scribe_cli_search(
    query: str = typer.Argument(...),
    top_k: int = typer.Option(8, "--top-k", "-k"),
    since: str | None = typer.Option(None, "--since", help="e.g. 1d, 7d, 2h, or ISO date"),
) -> None:
    """Search across durable scribe day-lines."""
    from videomemory.scribe.search import parse_relative
    from videomemory.scribe.search import scribe_search as do_search

    s = parse_relative(since) if since else None
    hits = do_search(query, top_k=top_k, since=s)
    if not hits:
        console.print("[yellow]no hits[/yellow]"); return
    t = Table(show_header=True, header_style="bold")
    t.add_column("date"); t.add_column("kind"); t.add_column("score", justify="right"); t.add_column("text")
    for h in hits:
        text = h["text"][:90] + ("…" if len(h["text"]) > 90 else "")
        t.add_row(h["date"], h["kind"], f"{h['score']:.3f}", text)
    console.print(t)


@scribe_app.command("forget")
def scribe_forget(
    since: str | None = typer.Option(None, "--since", help="e.g. 10m, 1h, 1d"),
    app: str | None = typer.Option(None, "--app"),
) -> None:
    """Delete captured frames + sessions + notes since a relative time, or for an app."""
    from videomemory.scribe.search import parse_relative
    from videomemory.scribe.store import forget_app, forget_since

    if since:
        t = parse_relative(since)
        r = forget_since(t)
        console.print(f"[green]forgot[/green] frames={r['frames']} sessions={r['sessions']}")
    elif app:
        r = forget_app(app)
        console.print(f"[green]forgot[/green] app={app} frames={r['frames']} sessions={r['sessions']}")
    else:
        console.print("[red]pass --since or --app[/red]"); raise typer.Exit(1)


@scribe_app.command("blocklist")
def scribe_blocklist(
    action: str = typer.Argument(..., help="add | remove | list"),
    target: str | None = typer.Argument(None),
    kind: str = typer.Option("app", "--kind", help="app or url"),
) -> None:
    """Manage scribe's app/url blocklist."""
    from videomemory.scribe import privacy as p

    if action == "list":
        apps, urls = p.blocklists()
        console.print("[bold]apps[/bold]"); [console.print(f"  - {a}") for a in apps]
        console.print("[bold]urls[/bold]"); [console.print(f"  - {u}") for u in urls]
        return
    if not target:
        console.print("[red]missing target[/red]"); raise typer.Exit(1)
    if action == "add":
        (p.add_url if kind == "url" else p.add_app)(target)
        console.print(f"[green]added[/green] {kind}: {target}")
    elif action == "remove":
        ok = (p.remove_url if kind == "url" else p.remove_app)(target)
        console.print(f"[{'green' if ok else 'yellow'}]{'removed' if ok else 'not in user list'}[/]: {target}")
    else:
        console.print(f"[red]unknown action: {action}[/red]"); raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
