"""MCP server exposing VideoMemory over stdio.

Wires the seven core tools described in the design plan. Frames are served as
MCP resources so the client can fetch them on demand rather than receive
base64-encoded blobs in every tool response.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import mcp.types as mt
from mcp.server import Server
from mcp.server.stdio import stdio_server

from videomemory.mcp.tools import (
    handle_get_frames,
    handle_get_timeline,
    handle_get_transcript,
    handle_ingest_video,
    handle_list_videos,
    handle_query_video,
    handle_semantic_search,
)

log = logging.getLogger(__name__)

TOOL_DEFS: list[mt.Tool] = [
    mt.Tool(
        name="ingest_video",
        description="Ingest a local video file or a URL (YouTube supported). Returns a job_id and video_id.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Path to a local video or a URL."},
            },
            "required": ["source"],
        },
    ),
    mt.Tool(
        name="list_videos",
        description="List all videos that have been ingested.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    mt.Tool(
        name="query_video",
        description="Ask a question about an ingested video. Returns top semantic chunks + selective frames + a brief answer when an LLM is available.",
        inputSchema={
            "type": "object",
            "properties": {
                "video_id": {"type": "string"},
                "query": {"type": "string"},
                "max_chunks": {"type": "integer", "default": 5},
                "max_frames": {"type": "integer", "default": 8},
                "include_frames": {"type": "boolean", "default": True},
            },
            "required": ["video_id", "query"],
        },
    ),
    mt.Tool(
        name="get_timeline",
        description="Return a timeline of an ingested video. Granularity: scene | chunk | event.",
        inputSchema={
            "type": "object",
            "properties": {
                "video_id": {"type": "string"},
                "granularity": {"type": "string", "enum": ["scene", "chunk", "event"], "default": "chunk"},
            },
            "required": ["video_id"],
        },
    ),
    mt.Tool(
        name="get_frames",
        description="Return up to N relevant keyframes for a video. Filter by query, exact time, or time range.",
        inputSchema={
            "type": "object",
            "properties": {
                "video_id": {"type": "string"},
                "query": {"type": "string"},
                "at_time": {"type": "number"},
                "range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["video_id"],
        },
    ),
    mt.Tool(
        name="semantic_search",
        description="Multimodal retrieval (transcript / OCR / visual / fused) over a video. Returns chunk_ids with scores.",
        inputSchema={
            "type": "object",
            "properties": {
                "video_id": {"type": "string"},
                "query": {"type": "string"},
                "modalities": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["transcript", "ocr", "visual", "fuse", "semantic"]},
                },
                "top_k": {"type": "integer", "default": 10},
            },
            "required": ["video_id", "query"],
        },
    ),
    mt.Tool(
        name="get_transcript",
        description="Fetch transcript segments, optionally filtered by speaker / time.",
        inputSchema={
            "type": "object",
            "properties": {
                "video_id": {"type": "string"},
                "speaker": {"type": "string"},
                "start": {"type": "number"},
                "end": {"type": "number"},
            },
            "required": ["video_id"],
        },
    ),
]

_TOOL_HANDLERS = {
    "ingest_video": handle_ingest_video,
    "list_videos": handle_list_videos,
    "query_video": handle_query_video,
    "get_timeline": handle_get_timeline,
    "get_frames": handle_get_frames,
    "semantic_search": handle_semantic_search,
    "get_transcript": handle_get_transcript,
}


def build_server(data_dir: Path) -> Server:
    server: Server = Server("videomemory")
    os.environ["VIDEOMEMORY_DATA_DIR"] = str(data_dir)

    @server.list_tools()
    async def _list_tools() -> list[mt.Tool]:
        return TOOL_DEFS

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[mt.TextContent]:
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return [mt.TextContent(type="text", text=json.dumps({"error": f"unknown tool: {name}"}))]
        try:
            result = await handler(arguments or {}, data_dir=data_dir)
        except Exception as exc:
            log.exception("tool %s failed", name)
            return [mt.TextContent(type="text", text=json.dumps({"error": str(exc)}))]
        text = json.dumps(result, indent=2)
        return [mt.TextContent(type="text", text=text)]

    @server.list_resources()
    async def _list_resources() -> list[mt.Resource]:
        # Frames are exposed as resources under videomemory://frames/<video_id>/<frame_id>.jpg
        # We don't enumerate all frames here (could be thousands); the client requests by URI.
        return []

    @server.read_resource()
    async def _read_resource(uri: str) -> str | bytes:
        # Accept videomemory://frames/<video_id>/<file>
        if not str(uri).startswith("videomemory://frames/"):
            raise ValueError(f"unsupported resource: {uri}")
        rest = str(uri).removeprefix("videomemory://frames/")
        try:
            video_id, fname = rest.split("/", 1)
        except ValueError as exc:
            raise ValueError(f"malformed frame URI: {uri}") from exc
        path = data_dir / "videos" / video_id / "frames" / fname
        if not path.exists():
            raise FileNotFoundError(str(path))
        return path.read_bytes()

    return server


async def serve_stdio(data_dir: Path = Path("./data")) -> None:
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    server = build_server(data_dir)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
