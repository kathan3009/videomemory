"""MCP server exposing videomemory over stdio.

9 tools: understand, skip, search, frames, look, shots, cutpoints, add, list.
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
from videomemory.cutpoints import suggest_cuts as one_suggest_cuts
from videomemory.frames import get_frames as multi_frames
from videomemory.ingest import ingest
from videomemory.library import list_videos as lib_list_videos
from videomemory.search import search as cross_search
from videomemory.search import skip as one_skip
from videomemory.shots import detect_shots as one_detect_shots
from videomemory.understand import understand as one_understand
from videomemory.visual_index import analyze as visual_analyze

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
                "music": {"type": "string", "description": "Path to the soundtrack for beat alignment (optional)."},
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
