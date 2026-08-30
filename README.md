<div align="center">

# 🎬 videomemory

**give Claude Code & Codex a real memory for video.**
local-first or hosted. private. one MCP server, thirteen tools.

[![MIT](https://img.shields.io/badge/license-MIT-black?style=flat-square)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab?style=flat-square)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-40%20passing-34d399?style=flat-square)](tests/)
[![Hosted](https://img.shields.io/badge/hosted-ready-8ee7ff?style=flat-square)]()
[![Stars](https://img.shields.io/github/stars/kathan3009/videomemory?style=flat-square&color=fbbf24)](https://github.com/kathan3009/videomemory)

</div>

```
you  ▸  use videomemory to skip to the part of <youtube_url> where they explain X

claude ▸  14:23  →  https://youtu.be/X?t=863
       ▸  "First, we install Tailwind by running npm install tailwindcss..."
       ▸  [shows you the frame at 14:23]
```

that's it. you don't open the video. claude does.

---

## install (60 seconds)

```bash
git clone https://github.com/kathan3009/videomemory
cd videomemory
./setup.sh
```

that's the whole thing. it'll install `ffmpeg`+`yt-dlp` if missing, fetch the ML models (~600 MB), and wire the MCP server into Claude Code automatically.

prefer to let Claude do it? clone the repo, open a Claude Code session in the directory, and say:

> *set this up*

it'll find the skill in `.claude/skills/` and run setup itself.

### hosted SaaS

The same engine now includes an authenticated Streamable HTTP MCP endpoint, account dashboard,
tenant-isolated storage, quotas, Razorpay subscriptions, guarded public-URL ingestion, and a
living context graph. Deploy the backend with the included hardened `Dockerfile`; deploy
`src/videomemory/web` with OpenAI Sites. Follow `src/videomemory/DEPLOYMENT.md`, `deploy.env.example`, and
`src/videomemory/web/env.example` for the required environment variables.

Hosted MCP clients connect to `https://<api-host>/mcp` with a dashboard-generated bearer key.

---

## what you get

once installed, every Claude Code & Codex session gets these tools:

| | tool | what it does |
|---|---|---|
| ⚡ | **`skip`**       | paste url + question. get timestamp + deep link + frame + transcript snippet. |
| 👁️ | **`look`**       | visually understand *any* video. query-aware frame selection → one labeled contact sheet (~16× fewer vision tokens). no transcript needed. |
| ✂️ | **`shots`**      | detect frame-accurate shot boundaries (cut points). returns an editable cut list — in/out per shot + keyframe. for montage/editing. |
| 🥁 | **`cutpoints`**  | *when exactly to cut* for a montage. motion curve (cut on motion / into holds) × music beat grid (lengths snapped to beats). frame-accurate sub-clips. |
| 🖼️ | **`frames`**     | sample N keyframes from any video. for visual stuff with no audio (comedy shorts, sports, silent demos). |
| 🎧 | **`understand`** | watch the video for you. returns bullets + chapter timestamps + transcript. |
| 📚 | **`search`**     | search across **every** video you've ever added. cross-video, semantic. |
| ➕ | **`add`** / **`list`** | library management. |
| ✣ | **`memory`** | recall the private context graph built from prior searches, videos, exact moments, and notes. |
| ✎ | **`note`** | attach a durable note or branch a new version from an earlier interpretation. |
| ◇ | **`remember_artifact`** | remember where an agent-made artifact lives, what it contains, how to access it, and its project/parent. |
| ⌕ | **`artifact_memory`** | recall artifacts and version history across Codex, Claude, Cursor, and the rest of the team. |

frames come back as `videomemory://...` URIs that Claude fetches with native vision. no base64 blobs in your context window.

---

## what makes it interesting

### ⚡ skip the bloat

```
"skip to where they explain JWT in <2-hour tutorial>"
                            ↓
                       45:12 → click
```

every dev's most-googled phrase: *"just give me the answer."* now Claude can.

### 👁️ look at any video — cheaply

`look` is generic visual understanding for **any** video (no transcript required). instead of dumping 16 full-res frames into context, it runs a cost-ordered funnel entirely on your machine:

```
ffmpeg ~1fps  →  dedup (perceptual hash + color, then CLIP semantics)
              →  query-aware top-k  →  MMR for time-diversity
              →  ONE labeled contact sheet  →  Claude's vision
```

the index is built once per video (and reused across questions); only the handful of frames relevant to *your* question get packed into a single labeled grid — **~16× fewer vision tokens** than sending them separately, at equal-or-better accuracy. text/OCR queries auto-fall-back to separate full-res frames (grids soften small text).

```bash
videomemory look https://youtu.be/X "when does the drone take off?"
```

grounded in the research (SeViLA: 73.8% on 4 query-selected frames · IG-VLM: a frame grid beats prior SOTA on 9/10 video-QA benchmarks · LVNet: 12 selected ≈ 90 uniform).

### 📚 your YouTube history is searchable

import Google Takeout once → every video you've ever watched is queryable forever.

```bash
videomemory history ~/Downloads/Takeout/YouTube*/history/watch-history.json --limit 200
```

then ask Claude: *"which video did I watch about Postgres index tuning?"*

### 👯 watch club

your library is one SQLite file (~MBs even for hundreds of videos — just transcripts + embeddings, no original video). hand it to a friend, they `videomemory import` it, and now their Claude knows what you know.

```bash
videomemory export my-library.sqlite     # → 4.2 MB
# (send to friend)
videomemory import my-library.sqlite     # ← merges into theirs
```

no servers. no accounts. just a file.

---

## how it actually works

```
URL  →  yt-dlp + ffmpeg  →  faster-whisper  →  30s text windows
                                                      ↓
                              bge-small-en-v1.5 embeddings
                                                      ↓
                                                 SQLite library
                                                      ↓
                       cosine retrieval  +  on-demand ffmpeg keyframes
                                                      ↓
                                     13 MCP tools  (stdio + HTTP transport)
                                                      ↓
                               Claude Code  ·  Codex  ·  any MCP client
```

`look` adds a parallel **visual** index: ffmpeg keyframes → MobileCLIP-S2 image embeddings → SQLite → query-aware retrieval + a contact-sheet packer. still no Qdrant, no OCR engine, no object detection, no cloud anything — just transcript + embeddings + cosine + CLIP + ffmpeg + the agent's own vision.

| | dep | size |
|---|---|---:|
| 🔊 | faster-whisper (small) | ~470 MB |
| 🧠 | bge-small-en-v1.5      | ~120 MB |
| 👁️ | MobileCLIP-S2 (open_clip) | ~150 MB |
| 🎬 | ffmpeg + yt-dlp        | tiny |
| 🗄️ | sqlite                | – |

in local mode, after the first model download: **fully offline.** no API keys required.

---

## you can also use it from the terminal

```bash
videomemory skip https://youtu.be/X "where do they configure Tailwind?"
videomemory look https://youtu.be/X "what's on screen when the error appears?"
videomemory shots https://youtu.be/X            # frame-accurate cut list
videomemory cutpoints clip.mp4 --music song.mp3 --beats 2   # beat+motion cut plan
videomemory frames https://youtu.be/X --count 8
videomemory understand https://youtu.be/X
videomemory search "Postgres index tuning"
videomemory list
videomemory history watch-history.json
videomemory export my-library.sqlite
videomemory import friends-library.sqlite
```

---

## codex / other MCP clients

`setup.sh` auto-registers with Claude Code. for everyone else, paste this into your client's MCP config:

```json
{
  "mcpServers": {
    "videomemory": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/videomemory", "videomemory", "mcp", "serve"]
    }
  }
}
```

then restart and ask away.

---

## stuff under the hood, for the curious

```
src/videomemory/
├── ingest.py            # yt-dlp → ffmpeg → faster-whisper → 30s windows
├── search.py            # skip() + search() via cosine
├── frames.py            # extract one or many keyframes
├── visual_index.py      # look(): the visual funnel (dedup → CLIP → retrieve → contact sheet)
├── clip_embed.py        # MobileCLIP-S2 image+text embedder (CLIP fallback)
├── shots.py             # shots(): frame-accurate scene-boundary detection (ffmpeg)
├── cutpoints.py         # cutpoints(): montage cut planning (motion curve × beat grid)
├── understand.py        # bullets + chapters (LLM if key present, else extractive)
├── library.py           # SQLite schema + CRUD + bundle export/import
├── memory_graph.py      # tenant-private searches ↔ videos ↔ moments ↔ branched notes
├── mcp_server.py        # stdio + hosted Streamable HTTP MCP, 13 tools
├── youtube_history.py   # Google Takeout parser
├── deps.py              # `videomemory setup` wizard
├── embed.py             # bge-small wrapper
├── types.py             # Pydantic schemas
├── cli.py               # typer CLI
└── config.py            # env knobs
```

read it in 20 minutes.

---

## v1.1 candidates (not yet in)

curious what you'd want most:

- 🎤 podcast RSS support
- 🌐 Loom / Twitch VOD / Vimeo
- 🧭 Chrome extension that auto-ingests as you watch
- 🔁 livestream / long-video segmented re-indexing
- 🌳 agentic frame escalation for `look` (request more frames when unsure)

open an issue with what you'd actually use.

---

## license

MIT. built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper) · [bge embeddings](https://huggingface.co/BAAI/bge-small-en-v1.5) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [MCP](https://modelcontextprotocol.io/) · [Anthropic Claude Code](https://claude.ai/code) · [OpenAI Codex](https://platform.openai.com/codex).

if this is useful, drop a ⭐ — that's the only thanks this project needs.
