"""MCP server exposing videomemory over stdio.

Video tools: understand, skip, search, frames, add, list.
Scribe tools (if scribe extras installed): scribe_search, scribe_today,
scribe_status, scribe_forget.
Frames served as `videomemory://frames/<video_id>/<file>` resources.
"""

from __future__ import annotations

import json
import logging

import mcp.types as mt
from mcp.server import Server
from mcp.server.stdio import stdio_server

from videomemory.config import data_dir, frame_dir
from videomemory.frames import get_frames as multi_frames
from videomemory.ingest import ingest
from videomemory.library import list_videos as lib_list_videos
from videomemory.search import search as cross_search
from videomemory.search import skip as one_skip
from videomemory.understand import understand as one_understand

log = logging.getLogger(__name__)

TOOL_DEFS: list[mt.Tool] = [
    mt.Tool(
        name="understand",
        description=(
            "Watch a YouTube/file URL for the user. Returns title, duration, "
            "4-8 bullet takeaways, chapter timestamps with deep links, and the full transcript."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube URL or local file path."},
            },
            "required": ["url"],
        },
    ),
    mt.Tool(
        name="skip",
        description=(
            "Skip to the exact moment in a video where the user's question is answered. "
            "Ingests if not cached. Returns timestamp, deep link (e.g. youtu.be/X?t=863), "
            "transcript excerpt, and frame URI."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "question": {"type": "string"},
            },
            "required": ["url", "question"],
        },
    ),
    mt.Tool(
        name="search",
        description=(
            "Search across every video in the user's library (Watch History). "
            "Returns the top hits across videos with timestamps and deep links."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    ),
    mt.Tool(
        name="frames",
        description=(
            "Sample N keyframes from a video and return them as fetchable image URIs. "
            "Use this for VISUAL videos (comedy shorts, sports, silent demos) where the "
            "audio doesn't describe what's happening — Claude can then look at the frames "
            "with its own vision. Pick exactly one of: count (N evenly-spaced frames), "
            "every (a frame every X seconds), or at (explicit timestamps). Default: count=8. "
            "Hard cap is 16 frames per call to stay within context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "count": {"type": "integer", "description": "N evenly-spaced frames across the whole video."},
                "every": {"type": "number", "description": "A frame every X seconds."},
                "at": {"type": "array", "items": {"type": "number"}, "description": "Explicit timestamps in seconds."},
            },
            "required": ["url"],
        },
    ),
    mt.Tool(
        name="add",
        description="Add a video to the library without asking a question (just ingest + index).",
        inputSchema={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ),
    mt.Tool(
        name="list",
        description="List videos currently in the library.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    mt.Tool(
        name="scribe_search",
        description=(
            "Search across the user's durable day digests (what scribe wrote about their "
            "screen activity each day). Returns matched lines with date + kind (did | learned | "
            "decided | todo | saw). Use this for questions like 'what did I work on last week?' "
            "or 'what did I learn about Postgres recently?'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "since": {"type": "string", "description": "relative (1d, 7d, 2h) or ISO date"},
                "top_k": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    ),
    mt.Tool(
        name="scribe_today",
        description="Return today's day-digest markdown (compiles it now if not yet written).",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    mt.Tool(
        name="scribe_status",
        description="Return scribe daemon status + live counts (ephemeral frames, durable days, etc.).",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    mt.Tool(
        name="scribe_forget",
        description=(
            "Delete captured frames + sessions since a relative time, or for a specific app. "
            "Privacy-critical: use when the user said something sensitive was on screen."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "10m, 1h, 1d, etc."},
                "app":   {"type": "string"},
            },
            "required": [],
        },
    ),
]


async def _handle(name: str, args: dict) -> dict:
    if name == "understand":
        s = await one_understand(args["url"])
        return s.model_dump(mode="json")

    if name == "skip":
        h = await one_skip(args["url"], args["question"])
        return h.model_dump(mode="json") if h else {"hit": None}

    if name == "search":
        hits = cross_search(args["query"], top_k=int(args.get("top_k", 5)))
        return {"hits": [h.model_dump(mode="json") for h in hits]}

    if name == "frames":
        frames = await multi_frames(
            args["url"],
            count=args.get("count"),
            every=args.get("every"),
            at=args.get("at"),
        )
        return {"frames": [f.model_dump(mode="json") for f in frames]}

    if name == "add":
        v = await ingest(args["url"])
        return v.model_dump(mode="json")

    if name == "list":
        return {"videos": [v.model_dump(mode="json") for v in lib_list_videos()]}

    if name == "scribe_search":
        from videomemory.scribe.search import parse_relative, scribe_search

        since = parse_relative(args["since"]) if args.get("since") else None
        hits = scribe_search(args["query"], top_k=int(args.get("top_k", 8)), since=since)
        return {"hits": hits}

    if name == "scribe_today":
        from datetime import date as _date

        from videomemory.scribe.digest import build_today_digest, days_dir

        today_md = days_dir() / f"{_date.today().isoformat()}.md"
        if not today_md.exists():
            out = await build_today_digest()
            if out is None:
                return {"markdown": "", "note": "no activity captured today"}
            today_md = out
        return {"date": _date.today().isoformat(), "markdown": today_md.read_text()}

    if name == "scribe_status":
        from videomemory.scribe import daemon as d
        from videomemory.scribe.store import stats as s_stats

        pid = d.is_running()
        return {
            "running": bool(pid),
            "pid": pid,
            "paused": d.is_paused(),
            **s_stats(),
        }

    if name == "scribe_forget":
        from videomemory.scribe.search import parse_relative
        from videomemory.scribe.store import forget_app, forget_since

        if args.get("since"):
            r = forget_since(parse_relative(args["since"]))
        elif args.get("app"):
            r = forget_app(args["app"])
        else:
            raise ValueError("pass 'since' or 'app'")
        return {"deleted": r}

    raise ValueError(f"unknown tool: {name}")


def build_server() -> Server:
    server: Server = Server("videomemory")

    @server.list_tools()
    async def _list_tools() -> list[mt.Tool]:
        return TOOL_DEFS

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[mt.TextContent]:
        try:
            result = await _handle(name, arguments or {})
        except Exception as exc:
            log.exception("tool %s failed", name)
            result = {"error": str(exc)}
        return [mt.TextContent(type="text", text=json.dumps(result, indent=2))]

    @server.list_resources()
    async def _list_resources() -> list[mt.Resource]:
        return []

    @server.read_resource()
    async def _read_resource(uri: str) -> str | bytes:
        s = str(uri)
        if not s.startswith("videomemory://frames/"):
            raise ValueError(f"unsupported resource: {uri}")
        rest = s.removeprefix("videomemory://frames/")
        try:
            video_id, fname = rest.split("/", 1)
        except ValueError as exc:
            raise ValueError(f"malformed frame URI: {uri}") from exc
        path = frame_dir(video_id) / fname
        if not path.exists():
            raise FileNotFoundError(str(path))
        return path.read_bytes()

    return server


async def serve_stdio() -> None:
    _ = data_dir()  # ensures the dir exists before any tool runs
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


__all__ = ["build_server", "serve_stdio", "TOOL_DEFS"]
