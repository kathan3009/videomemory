"""VideoMemory CLI — `videomemory <subcommand>`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from videomemory import __version__

app = typer.Typer(
    name="videomemory",
    help="VideoMemory — semantic temporal memory for videos, exposed to AI agents via MCP.",
    no_args_is_help=False,
    add_completion=False,
    invoke_without_command=True,
)

mcp_app = typer.Typer(help="MCP server commands.")
frames_app = typer.Typer(help="Frame search commands.")
app.add_typer(mcp_app, name="mcp")
app.add_typer(frames_app, name="frames")

console = Console()


@app.callback()
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
) -> None:
    if version:
        console.print(f"videomemory {__version__}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit(0)


@app.command()
def ingest(
    source: str = typer.Argument(..., help="Video path or URL (YouTube supported)."),
    data_dir: Path = typer.Option(
        Path("./data"), "--data-dir", help="Where to store artifacts and the SQLite DB."
    ),
    config: Path | None = typer.Option(None, "--config", help="Optional YAML config."),
) -> None:
    """Run the full ingest pipeline for a video."""
    from videomemory.pipeline.runner import run_ingest

    job = asyncio.run(run_ingest(source=source, data_dir=data_dir, config_path=config))
    console.print(f"[green]Done.[/green] video_id={job.video_id}")
    console.print(f"Artifacts: {job.artifacts_dir}")


@app.command()
def ask(
    video_id: str = typer.Argument(..., help="Video ID returned by `ingest`."),
    query: str = typer.Argument(..., help="Natural-language question."),
    data_dir: Path = typer.Option(Path("./data"), "--data-dir"),
    max_chunks: int = typer.Option(5, "--max-chunks"),
    max_frames: int = typer.Option(8, "--max-frames"),
    json_out: bool = typer.Option(False, "--json", help="Emit raw JSON."),
) -> None:
    """Ask a question about an ingested video."""
    from videomemory.query.engine import answer_question

    result = asyncio.run(
        answer_question(
            video_id=video_id,
            query=query,
            data_dir=data_dir,
            max_chunks=max_chunks,
            max_frames=max_frames,
        )
    )
    if json_out:
        console.print_json(data=result.model_dump(mode="json"))
        return

    if result.answer:
        console.print(f"\n[bold]{result.answer}[/bold]\n")

    table = Table(title="Top chunks")
    table.add_column("time")
    table.add_column("score", justify="right")
    table.add_column("summary")
    for c in result.chunks:
        table.add_row(f"{c.start:.1f}–{c.end:.1f}s", f"{c.score:.3f}", c.summary[:80])
    console.print(table)

    if result.frames:
        console.print(f"\n[dim]{len(result.frames)} frame(s) returned[/dim]")
        for f in result.frames:
            console.print(f"  • t={f.timestamp:.1f}s  score={f.score:.3f}  why={f.why}")


@frames_app.command("search")
def frames_search(
    video_id: str = typer.Argument(...),
    query: str = typer.Option(..., "--query", "-q"),
    limit: int = typer.Option(8, "--limit"),
    data_dir: Path = typer.Option(Path("./data"), "--data-dir"),
) -> None:
    """Selective frame recall."""
    from videomemory.retrieval.frame_recall import recall_frames

    frames = asyncio.run(recall_frames(video_id=video_id, query=query, limit=limit, data_dir=data_dir))
    console.print_json(data=[f.model_dump(mode="json") for f in frames])


@app.command()
def list() -> None:  # noqa: A001 - intentional shadow for CLI verb
    """List ingested videos."""
    from videomemory.storage.sqlite_db import list_videos_sync

    videos = list_videos_sync()
    table = Table(title="Videos")
    for col in ("video_id", "title", "duration", "status", "ingested_at"):
        table.add_column(col)
    for v in videos:
        table.add_row(
            v["video_id"],
            v.get("title") or "",
            f"{v.get('duration', 0):.0f}s",
            v.get("status", ""),
            v.get("ingested_at", ""),
        )
    console.print(table)


@app.command()
def resume(
    job_id: str = typer.Argument(..., help="Job ID from a previous interrupted ingest."),
    data_dir: Path = typer.Option(Path("./data"), "--data-dir"),
) -> None:
    """Resume an interrupted ingest job from its last completed stage."""
    from videomemory.pipeline.resume import resume_job

    job = asyncio.run(resume_job(job_id=job_id, data_dir=data_dir))
    console.print(f"[green]Resumed[/green] job_id={job.job_id} video_id={job.video_id}")


@mcp_app.command("serve")
def mcp_serve(
    data_dir: Path = typer.Option(Path("./data"), "--data-dir"),
) -> None:
    """Start the MCP server over stdio (for Claude Desktop / Cursor / Windsurf / VSCode)."""
    from videomemory.mcp.server import serve_stdio

    asyncio.run(serve_stdio(data_dir=data_dir))


@app.command()
def export(
    video_id: str = typer.Argument(...),
    format: str = typer.Option("json", "--format", help="json | markdown | yaml | llm-context"),
    out: Path | None = typer.Option(None, "--out"),
    data_dir: Path = typer.Option(Path("./data"), "--data-dir"),
) -> None:
    """Export memory for a video in the chosen format."""
    from videomemory.exporters import export_memory

    text = asyncio.run(export_memory(video_id=video_id, fmt=format, data_dir=data_dir))
    if out:
        out.write_text(text)
        console.print(f"[green]Wrote[/green] {out}")
    else:
        if format == "json":
            console.print_json(text)
        else:
            console.print(text)


def main() -> None:  # pragma: no cover - entry shim
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
