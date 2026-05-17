"""MCP server exposing videomemory over stdio.

6 tools: understand, skip, search, frames, add, list.
Frames are served as `videomemory://frames/<video_id>/<file>` resources so
clients can fetch them on demand rather than receiving base64 blobs.
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
