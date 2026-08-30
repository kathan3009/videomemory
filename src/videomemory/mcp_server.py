"""MCP server exposing videomemory over stdio.

13 tools: video understanding, durable video memory, and organization-wide artifact memory.
Frames are served as `videomemory://frames/<video_id>/<file>` resources so
clients can fetch them on demand rather than receiving base64 blobs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

import mcp.types as mt
from mcp.server import Server
from mcp.server.stdio import stdio_server

from videomemory.artifact_memory import artifact_memory, remember_artifact
from videomemory.config import data_dir, frame_dir, hosted_mode
from videomemory.control import record_usage, usage_summary
from videomemory.cutpoints import suggest_cuts as one_suggest_cuts
from videomemory.frames import get_frames as multi_frames
from videomemory.ingest import cache_public_audio, ingest, video_id_for
from videomemory.library import get_video
from videomemory.library import list_videos as lib_list_videos
from videomemory.memory_graph import add_note, graph_snapshot, recall_context, record_tool_memory
from videomemory.search import search as cross_search
from videomemory.search import skip as one_skip
from videomemory.shots import detect_shots as one_detect_shots
from videomemory.tenant import current_tenant
from videomemory.understand import understand as one_understand
from videomemory.url_safety import validate_public_url
from videomemory.visual_index import analyze as visual_analyze

log = logging.getLogger(__name__)
_expensive_tools = {"understand", "skip", "frames", "look", "shots", "cutpoints", "add"}
_tool_semaphore = asyncio.Semaphore(max(1, int(os.environ.get("VIDEOMEMORY_MCP_CONCURRENCY", "2"))))

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
        name="look",
        description=(
            "Visually understand ANY video and answer a question about what's on screen — "
            "token-efficiently. Builds a deduped CLIP index of the video once (no transcription), "
            "then retrieves only the handful of frames relevant to your question and packs them into "
            "a SINGLE labeled contact-sheet image (~16x cheaper than sending many frames). Use this "
            "over `frames` for visual Q&A ('when does X happen', 'what is the person doing', 'find the "
            "shot with Y'). Returns sheet_uri (fetch + view it) plus the chosen frames' timestamps and "
            "deep links. For fine text/OCR it auto-returns separate full-res frames instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube URL or local file path."},
                "question": {"type": "string", "description": "What you want to understand visually."},
                "k": {"type": "integer", "default": 9, "description": "How many frames to select (default 9)."},
                "packing": {
                    "type": "string",
                    "enum": ["auto", "sheet", "separate"],
                    "default": "auto",
                    "description": "auto = contact sheet, separate frames for OCR queries.",
                },
            },
            "required": ["url", "question"],
        },
    ),
    mt.Tool(
        name="shots",
        description=(
            "Detect frame-accurate shot boundaries (cut points) in a video. Returns an editable "
            "cut list: each shot's in/out timestamps, duration, a deep link to the in-point, and a "
            "representative keyframe URI. Use this for editing/montage work — building an EDL, finding "
            "where to cut, or counting distinct shots. Complements `look` (visual Q&A). Lower the "
            "threshold to detect more (subtler) cuts; raise it for only hard cuts."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube URL or local file path."},
                "threshold": {"type": "number", "description": "Scene score 0..1 (default 0.4). Lower = more cuts."},
                "min_shot": {"type": "number", "description": "Merge shots shorter than this many seconds (default 0.6)."},
            },
            "required": ["url"],
        },
    ),
    mt.Tool(
        name="cutpoints",
        description=(
            "Suggest frame-accurate cut points for a take — the 'when exactly do I cut' tool for "
            "montage assembly. Combines a per-frame motion curve (cut into stable framing, out on "
            "motion) with a music beat grid (clip lengths snapped to whole beats so cuts land on the "
            "beat). Returns sub-clips with in/out timestamps, duration in beats, deep links, and a "
            "keyframe. Pass `music` (path to the soundtrack) for beat alignment; without it, falls "
            "back to motion + an even target length. Use `look` first to pick WHICH take/moment, then "
            "this for the exact frames."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube URL or local file path of the take."},
                "music": {
                    "type": "string",
                    "description": (
                        "Optional soundtrack path in local mode, or a public audio/video URL "
                        "when using the hosted MCP endpoint."
                    ),
                },
                "beats_per_cut": {"type": "integer", "default": 2, "description": "Beats each cut should span (default 2)."},
                "target_len": {"type": "number", "default": 2.0, "description": "Fallback clip length in seconds when no music (default 2.0)."},
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
        name="memory",
        description=(
            "Recall the authenticated user's context brain: prior searches, videos, moments, "
            "relationships, and notes. Pass a query for relevant context, or omit it for a recent graph snapshot."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic or context to recall (optional)."},
                "limit": {"type": "integer", "default": 12},
            },
            "required": [],
        },
    ),
    mt.Tool(
        name="note",
        description=(
            "Attach a durable note to a video in memory. Pass parent_note_id to create a new "
            "version or branch without overwriting the earlier thought."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "video_id": {"type": "string"},
                "url": {"type": "string", "description": "Known video URL; used when video_id is omitted."},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "parent_note_id": {"type": "string"},
            },
            "required": ["title", "body"],
        },
    ),
    mt.Tool(
        name="remember_artifact",
        description=(
            "Remember an agent-created artifact: where it lives, what it is, how to access it, "
            "its useful content, and its project/parent. The same locator creates a new version "
            "when content changes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "locator": {"type": "string", "description": "File path, repository URL, document URL, or durable identifier."},
                "kind": {"type": "string", "enum": ["code", "document", "image", "video", "audio", "dataset", "design", "report", "other"]},
                "access_instructions": {"type": "string"},
                "summary": {"type": "string"},
                "content": {"type": "string", "description": "Optional searchable text or compact artifact body (max 200k characters)."},
                "project": {"type": "string"},
                "agent": {"type": "string"},
                "parent_artifact_id": {"type": "string"},
                "metadata": {"type": "object", "additionalProperties": True},
            },
            "required": ["title", "locator"],
        },
    ),
    mt.Tool(
        name="artifact_memory",
        description=(
            "Recall artifacts by title, content, project, or locator. Pass artifact_id to retrieve "
            "its version history and access context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "artifact_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "include_content": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    ),
]


async def _handle(name: str, args: dict) -> dict:
    if hosted_mode() and "url" in args:
        args = {**args, "url": await validate_public_url(str(args["url"]))}
    if hosted_mode() and name == "cutpoints" and args.get("music"):
        music_url = await validate_public_url(str(args["music"]))
        args = {**args, "music": str(await cache_public_audio(music_url))}
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

    if name == "look":
        a = await visual_analyze(
            args["url"],
            args["question"],
            k=int(args.get("k", 9)),
            packing=args.get("packing", "auto"),
        )
        return a.model_dump(mode="json")

    if name == "shots":
        sl = await one_detect_shots(
            args["url"],
            threshold=args.get("threshold"),
            min_shot=args.get("min_shot"),
        )
        return sl.model_dump(mode="json")

    if name == "cutpoints":
        cp = await one_suggest_cuts(
            args["url"],
            music=args.get("music"),
            beats_per_cut=int(args.get("beats_per_cut", 2)),
            target_len=float(args.get("target_len", 2.0)),
        )
        return cp.model_dump(mode="json")

    if name == "add":
        v = await ingest(args["url"])
        return v.model_dump(mode="json")

    if name == "list":
        return {"videos": [v.model_dump(mode="json") for v in lib_list_videos()]}

    if name == "memory":
        query = str(args.get("query", "")).strip()
        limit = int(args.get("limit", 12))
        return recall_context(query, limit) if query else graph_snapshot(limit=max(20, limit))

    if name == "note":
        video_id = str(args.get("video_id", "")).strip()
        if not video_id and args.get("url"):
            video_id = video_id_for(str(args["url"]))
        if not video_id:
            raise ValueError("video_id or url is required")
        return add_note(
            video_id,
            str(args.get("title", "")),
            str(args.get("body", "")),
            str(args["parent_note_id"]) if args.get("parent_note_id") else None,
        )

    if name == "remember_artifact":
        return remember_artifact(
            title=str(args.get("title", "")),
            locator=str(args.get("locator", "")),
            kind=str(args.get("kind", "other")),
            access_instructions=str(args.get("access_instructions", "")),
            summary=str(args.get("summary", "")),
            content=str(args.get("content", "")),
            project=str(args.get("project", "")),
            agent=str(args.get("agent", "")),
            parent_artifact_id=str(args["parent_artifact_id"]) if args.get("parent_artifact_id") else None,
            metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else {},
        )

    if name == "artifact_memory":
        return artifact_memory(
            str(args.get("query", "")),
            artifact_id=str(args["artifact_id"]) if args.get("artifact_id") else None,
            limit=int(args.get("limit", 20)),
            include_content=bool(args.get("include_content", False)),
        )

    raise ValueError(f"unknown tool: {name}")


def build_server() -> Server:
    server: Server = Server(
        "videomemory",
        version="1.0.0",
        website_url=os.environ.get("VIDEOMEMORY_WEBSITE_URL", "https://github.com/kathan3009/videomemory"),
        instructions=(
            "Videomemory gives agents a private searchable memory for video. Use skip for exact "
            "answers, look for visual questions, understand for a whole-video brief, and search "
            "for the authenticated user's library. Call remember_artifact after creating durable "
            "work, and artifact_memory before recreating it. Ingestion can take time; never invent a result."
        ),
    )

    @server.list_tools()
    async def _list_tools() -> list[mt.Tool]:
        return TOOL_DEFS

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[mt.ContentBlock]:
        tenant = current_tenant()
        source = str((arguments or {}).get("url", ""))
        source_id = video_id_for(source) if source else None
        was_indexed = bool(source_id and get_video(source_id))
        try:
            if tenant and hosted_mode():
                usage = usage_summary(tenant)
                if usage["totals"].get("mcp_calls", 0) >= usage["limits"]["mcp_calls"]:
                    raise ValueError("monthly MCP call limit reached")
                if source_id and not was_indexed:
                    if usage["totals"].get("videos", 0) >= usage["limits"]["videos"]:
                        raise ValueError("monthly video limit reached")
                    if usage["totals"].get("minutes", 0) >= usage["limits"]["minutes"]:
                        raise ValueError("monthly indexed-minute limit reached")
            if name in _expensive_tools:
                async with _tool_semaphore:
                    result = await _handle(name, arguments or {})
            else:
                result = await _handle(name, arguments or {})
        except Exception as exc:
            log.exception("tool %s failed", name)
            result = {"error": str(exc)}
        if tenant and hosted_mode():
            record_usage(tenant, "mcp_calls", 1, {"tool": name})
            indexed = get_video(source_id) if source_id else None
            if indexed and not was_indexed:
                record_usage(tenant, "videos", 1, {"video_id": indexed.video_id, "via": "mcp"})
                record_usage(
                    tenant,
                    "minutes",
                    max(0, indexed.duration / 60),
                    {"video_id": indexed.video_id, "via": "mcp"},
                )
        record_tool_memory(name, arguments or {}, result)
        blocks: list[mt.ContentBlock] = [mt.TextContent(type="text", text=json.dumps(result, indent=2))]
        seen: set[str] = set()

        def add_frame_links(value: object) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.endswith("uri") and isinstance(item, str) and item.startswith("videomemory://frames/"):
                        if item not in seen:
                            seen.add(item)
                            blocks.append(
                                mt.ResourceLink(
                                    type="resource_link",
                                    name=item.rsplit("/", 1)[-1],
                                    title="Videomemory frame",
                                    uri=item,
                                    mimeType="image/jpeg",
                                    description="A tenant-private video frame returned by this tool call.",
                                )
                            )
                    else:
                        add_frame_links(item)
            elif isinstance(value, list):
                for item in value:
                    add_frame_links(item)

        add_frame_links(result)
        return blocks

    @server.list_resources()
    async def _list_resources() -> list[mt.Resource]:
        return []

    @server.list_resource_templates()
    async def _list_resource_templates() -> list[mt.ResourceTemplate]:
        return [
            mt.ResourceTemplate(
                name="video-frame",
                title="Videomemory frame",
                uriTemplate="videomemory://frames/{video_id}/{filename}",
                description="A frame generated for a video in the authenticated tenant's library.",
                mimeType="image/jpeg",
            )
        ]

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
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,96}", video_id):
            raise ValueError(f"malformed frame URI: {uri}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}\.(?:jpe?g|png)", fname, re.IGNORECASE):
            raise ValueError(f"malformed frame URI: {uri}")
        base = frame_dir(video_id).resolve()
        path = (base / fname).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise FileNotFoundError(str(path))
        return path.read_bytes()

    return server


async def serve_stdio() -> None:
    _ = data_dir()  # ensures the dir exists before any tool runs
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


__all__ = ["build_server", "serve_stdio", "TOOL_DEFS"]
