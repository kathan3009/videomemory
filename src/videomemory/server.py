"""Hosted surface: single-page demo + REST + HTTP MCP transport.

Same library code as the stdio server — just bolted to FastAPI for the public host.
"""

from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from videomemory.config import frame_dir
from videomemory.ingest import ingest
from videomemory.library import list_videos
from videomemory.mcp_server import _handle
from videomemory.search import search as cross_search
from videomemory.search import skip as one_skip
from videomemory.understand import understand as one_understand

app = FastAPI(
    title="videomemory",
    version="0.2.0",
    description="The video understanding layer for Claude Code & Codex.",
)


# ---------- REST surface (mirrors MCP tools) ----------


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    return "ok"


@app.post("/skip")
async def api_skip(body: dict) -> dict:
    url = body.get("url"); q = body.get("question")
    if not url or not q:
        raise HTTPException(400, "url and question required")
    h = await one_skip(url, q)
    return {"hit": h.model_dump(mode="json") if h else None}


@app.post("/search")
async def api_search(body: dict) -> dict:
    q = body.get("query"); k = int(body.get("top_k", 5))
    if not q:
        raise HTTPException(400, "query required")
    hits = cross_search(q, top_k=k)
    return {"hits": [h.model_dump(mode="json") for h in hits]}


@app.post("/understand")
async def api_understand(body: dict) -> dict:
    url = body.get("url")
    if not url:
        raise HTTPException(400, "url required")
    s = await one_understand(url)
    return s.model_dump(mode="json")


@app.post("/add")
async def api_add(body: dict) -> dict:
    url = body.get("url")
    if not url:
        raise HTTPException(400, "url required")
    v = await ingest(url)
    return v.model_dump(mode="json")


@app.get("/videos")
async def api_videos() -> dict:
    return {"videos": [v.model_dump(mode="json") for v in list_videos()]}


@app.get("/frames/{video_id}/{name}")
async def api_frame(video_id: str, name: str) -> FileResponse:
    p = frame_dir(video_id) / name
    if not p.exists():
        raise HTTPException(404, "frame not found")
    return FileResponse(p)


# ---------- HTTP MCP transport ----------
# A minimal JSON-RPC-over-HTTP shim that speaks MCP's call_tool / list_tools.
# We keep this simple so we don't depend on internals of the SDK that might
# move between releases.

from videomemory.mcp_server import TOOL_DEFS


@app.post("/mcp")
async def mcp_jsonrpc(request: Request) -> JSONResponse:
    """A pragmatic JSON-RPC endpoint speaking MCP semantics.

    Supports:
      - initialize           → server info
      - tools/list           → registered tools
      - tools/call           → invoke handler
      - resources/read       → fetch a videomemory:// resource
    """
    try:
        msg = await request.json()
    except Exception as exc:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": str(exc)}, "id": None})

    rid = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "videomemory", "version": "0.2.0"},
            }
        elif method == "tools/list":
            result = {"tools": [t.model_dump(mode="json") for t in TOOL_DEFS]}
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            payload = await _handle(name, args)
            result = {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}
        elif method == "resources/read":
            uri = params.get("uri", "")
            if not uri.startswith("videomemory://frames/"):
                raise ValueError("unsupported resource")
            rest = uri.removeprefix("videomemory://frames/")
            vid, fname = rest.split("/", 1)
            p = frame_dir(vid) / fname
            if not p.exists():
                raise FileNotFoundError(uri)
            import base64

            result = {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "image/jpeg",
                        "blob": base64.b64encode(p.read_bytes()).decode(),
                    }
                ]
            }
        else:
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"method not found: {method}"}, "id": rid}
            )
    except Exception as exc:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32000, "message": str(exc)}, "id": rid}
        )

    return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result})


# ---------- Single-page demo ----------


DEMO_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>videomemory · the video understanding layer for Claude Code & Codex</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root { color-scheme: dark; --bg:#0b0f17; --fg:#e7ecf3; --muted:#94a3b8; --accent:#34d399; --card:#0f1622; --border:#1f2937; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif; background:var(--bg); color:var(--fg); }
  .wrap { max-width: 760px; margin: 0 auto; padding: 64px 24px 96px; }
  h1 { font-size: 28px; letter-spacing: -0.01em; margin: 0 0 8px; display:flex; gap:10px; align-items:center; }
  h1 .dot { width:10px; height:10px; border-radius:999px; background:var(--accent); display:inline-block; }
  .tag { color: var(--muted); font-size: 14px; margin-bottom: 32px; }
  .card { background: var(--card); border:1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 18px; }
  label { display:block; font-size:12px; text-transform:uppercase; color:var(--muted); letter-spacing:.06em; margin-bottom: 6px; }
  input, button { font:inherit; }
  input[type=text] { width:100%; padding:11px 12px; background:#0a1019; color:var(--fg); border:1px solid var(--border); border-radius:8px; outline:none; }
  input[type=text]:focus { border-color:#3a4f6f; }
  .row { display:flex; gap:10px; }
  .row > * { flex: 1; }
  button.go { background: var(--accent); color:#0b0f17; border: 0; border-radius: 8px; padding: 11px 16px; font-weight: 600; cursor: pointer; }
  button.go:disabled { opacity:.55; cursor:not-allowed; }
  .answer { margin-top: 20px; }
  .answer .ts { font-variant-numeric: tabular-nums; color: var(--accent); font-weight: 700; }
  .answer .why { color: var(--muted); font-size: 13px; }
  pre { background: #08101b; border:1px solid var(--border); border-radius:8px; padding:12px; overflow:auto; }
  a { color: #93c5fd; }
  .nav { margin-top: 24px; display:flex; gap:18px; color:var(--muted); font-size: 14px; }
  .nav a { color: var(--muted); text-decoration: none; }
  .nav a:hover { color: var(--fg); }
  .install { background:#08101b; border:1px solid var(--border); border-radius:8px; padding:14px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; white-space: pre-wrap; }
  .footer { color: var(--muted); font-size: 12px; margin-top: 28px; }
  .frame { margin-top:14px; border:1px solid var(--border); border-radius: 8px; max-width:100%; }
</style>
</head>
<body>
  <div class="wrap">
    <h1><span class="dot"></span> videomemory</h1>
    <div class="tag">the video understanding layer for Claude Code &amp; Codex · paste a URL, ask anything</div>

    <div class="card">
      <label for="url">YouTube URL</label>
      <input id="url" type="text" placeholder="https://youtu.be/BM70fDqUo3c" />
      <div style="height:12px"></div>
      <label for="q">Question</label>
      <div class="row">
        <input id="q" type="text" placeholder="when do they actually configure Tailwind?" />
        <button class="go" id="go">Skip to it →</button>
      </div>
      <div class="answer" id="answer"></div>
    </div>

    <div class="card">
      <label>Install in Claude Code (one line)</label>
      <div class="install">claude mcp add -s user videomemory https://example.com/mcp --transport http</div>
      <div style="height:8px"></div>
      <label>Install in Codex (add to your MCP config)</label>
      <div class="install">{
  "mcpServers": {
    "videomemory": {
      "url": "https://example.com/mcp",
      "transport": "http"
    }
  }
}</div>
    </div>

    <div class="nav">
      <a href="https://github.com/kathan3009/videomemory" target="_blank">GitHub ↗</a>
      <a href="/healthz">healthz</a>
      <a href="/docs">api docs</a>
    </div>
    <div class="footer">Powered by faster-whisper + bge-small. Library data is anonymous &amp; shared across users (same URL → cached once).</div>
  </div>
<script>
const $ = (s) => document.querySelector(s);
async function run() {
  const url = $("#url").value.trim();
  const q = $("#q").value.trim();
  if (!url || !q) return;
  const btn = $("#go"); btn.disabled = true; btn.textContent = "Watching…";
  $("#answer").innerHTML = "<div class='why'>Transcribing if needed — this is fast on cached videos, slower (~1–3 min) on the first ingest.</div>";
  try {
    const r = await fetch("/skip", { method:"POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({url, question: q}) });
    const j = await r.json();
    const h = j.hit;
    if (!h) { $("#answer").innerHTML = "<div class='why'>No match.</div>"; return; }
    const html = `
      <div><span class='ts'>${h.timestamp_human}</span> — <a href="${h.deep_link}" target="_blank">${h.deep_link}</a></div>
      <p>${escapeHtml(h.transcript_excerpt)}</p>
      <div class='why'>score=${h.score.toFixed(3)} · ${h.title ?? h.video_id}</div>
    `;
    $("#answer").innerHTML = html;
  } catch (e) {
    $("#answer").innerHTML = `<div class='why'>Error: ${escapeHtml(String(e))}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "Skip to it →";
  }
}
function escapeHtml(s){return s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"})[c]);}
$("#go").addEventListener("click", run);
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return DEMO_HTML
