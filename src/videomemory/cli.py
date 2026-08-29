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
  videomemory mcp serve-http   # hosted Streamable HTTP MCP + web API
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


@app.command(name="look")
def cmd_look(
    url: str = typer.Argument(...),
    question: str = typer.Argument(...),
    k: int = typer.Option(9, "--k", "-k", help="How many frames to select."),
    packing: str = typer.Option("auto", "--packing", help="auto | sheet | separate"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Visually understand any video: query-aware frame selection → contact sheet."""
    import asyncio as _asyncio

    from videomemory.visual_index import analyze

    a = _asyncio.run(analyze(url, question, k=k, packing=packing))
    if json_out:
        console.print_json(data=a.model_dump(mode="json")); return
    console.print(
        f"[bold]{a.video_id}[/bold]  ·  {a.candidates_scanned} candidates → "
        f"{a.indexed_frames} indexed → {len(a.frames)} selected  ·  packing=[cyan]{a.packing}[/cyan]"
    )
    if a.sheet_uri:
        console.print(f"  contact sheet: [green]{a.sheet_uri}[/green]")
    for i, f in enumerate(a.frames, 1):
        console.print(f"  {i}. [green]{f.timestamp_human}[/green]  score={f.score:.3f}  {f.deep_link}")
    console.print(f"\n[dim]{a.guidance}[/dim]")


@app.command(name="shots")
def cmd_shots(
    url: str = typer.Argument(...),
    threshold: float = typer.Option(None, "--threshold", "-t", help="Scene score 0..1 (default 0.4)."),
    min_shot: float = typer.Option(None, "--min-shot", help="Merge shots shorter than N seconds."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Detect frame-accurate shot boundaries (cut points) → editable cut list."""
    import asyncio as _asyncio

    from videomemory.shots import detect_shots

    sl = _asyncio.run(detect_shots(url, threshold=threshold, min_shot=min_shot))
    if json_out:
        console.print_json(data=sl.model_dump(mode="json")); return
    console.print(f"[bold]{sl.video_id}[/bold]  ·  {len(sl.shots)} shots  ·  {sl.duration:.1f}s  ·  thr={sl.threshold}")
    t = Table(show_header=True, header_style="bold")
    t.add_column("#", justify="right"); t.add_column("in"); t.add_column("out"); t.add_column("dur", justify="right")
    for s in sl.shots:
        t.add_row(str(s.index), s.start_human, s.end_human, f"{s.duration_seconds:.1f}s")
    console.print(t)


@app.command(name="cutpoints")
def cmd_cutpoints(
    url: str = typer.Argument(...),
    music: str = typer.Option(None, "--music", "-m", help="Soundtrack path for beat alignment."),
    beats_per_cut: int = typer.Option(2, "--beats", help="Beats each cut spans."),
    target_len: float = typer.Option(2.0, "--target-len", help="Fallback clip length (no music)."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Suggest frame-accurate cut points (motion × beat) for montage assembly."""
    import asyncio as _asyncio

    from videomemory.cutpoints import suggest_cuts

    cp = _asyncio.run(suggest_cuts(url, music=music, beats_per_cut=beats_per_cut, target_len=target_len))
    if json_out:
        console.print_json(data=cp.model_dump(mode="json")); return
    bpm = f"{cp.bpm:.1f} BPM" if cp.bpm else "no beat grid"
    console.print(f"[bold]{cp.video_id}[/bold]  ·  {len(cp.segments)} cuts  ·  {cp.duration:.1f}s  ·  {bpm}")
    t = Table(show_header=True, header_style="bold")
    t.add_column("#", justify="right"); t.add_column("in"); t.add_column("out")
    t.add_column("dur", justify="right"); t.add_column("beats", justify="right"); t.add_column("in→out")
    for s in cp.segments:
        t.add_row(str(s.index), s.in_human, s.out_human, f"{s.duration_seconds:.2f}s",
                  f"{s.beats:.0f}" if s.beats else "–", f"{s.in_kind}→{s.out_kind}")
    console.print(t)
    console.print(f"[dim]{cp.notes}[/dim]")


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


@mcp_app.command("serve-http")
def mcp_serve_http(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8080, "--port", envvar="PORT"),
) -> None:
    """Start the authenticated hosted API and Streamable HTTP MCP server."""
    os.environ["VIDEOMEMORY_HOSTED"] = "1"
    import uvicorn

    uvicorn.run("videomemory.saas_api:app", host=host, port=port, proxy_headers=True)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
