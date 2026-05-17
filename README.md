<div align="center">

# 🎬 videomemory

**give Claude Code & Codex eyes for video.**
local. private. one MCP server, six tools, zero API keys.

[![MIT](https://img.shields.io/badge/license-MIT-black?style=flat-square)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab?style=flat-square)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-27%20passing-34d399?style=flat-square)](tests/)
[![No cloud](https://img.shields.io/badge/cloud-none-ff6b6b?style=flat-square)]()
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

---

## what you get

once installed, every Claude Code & Codex session gets these tools:

| | tool | what it does |
|---|---|---|
| ⚡ | **`skip`**       | paste url + question. get timestamp + deep link + frame + transcript snippet. |
| 🖼️ | **`frames`**     | sample N keyframes from any video. for visual stuff with no audio (comedy shorts, sports, silent demos). |
| 🎧 | **`understand`** | watch the video for you. returns bullets + chapter timestamps + transcript. |
| 📚 | **`search`**     | search across **every** video you've ever added. cross-video, semantic. |
| ➕ | **`add`** / **`list`** | library management. |

frames come back as `videomemory://...` URIs that Claude fetches with native vision. no base64 blobs in your context window.

---

## three things that make it interesting

### ⚡ skip the bloat

```
"skip to where they explain JWT in <2-hour tutorial>"
                            ↓
                       45:12 → click
```

every dev's most-googled phrase: *"just give me the answer."* now Claude can.

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
                                      6 MCP tools  (stdio transport)
                                                      ↓
                               Claude Code  ·  Codex  ·  any MCP client
```

**deliberately minimal.** no Qdrant, no CLIP, no OCR, no object detection, no scene graphs, no LLM-call summarization, no cloud anything. just transcript + embeddings + cosine + ffmpeg + the agent's own vision.

| | dep | size |
|---|---|---:|
| 🔊 | faster-whisper (small) | ~470 MB |
| 🧠 | bge-small-en-v1.5      | ~120 MB |
| 🎬 | ffmpeg + yt-dlp        | tiny |
| 🗄️ | sqlite                | – |

after first run: **fully offline.** no API keys, ever.

---

## you can also use it from the terminal

```bash
videomemory skip https://youtu.be/X "where do they configure Tailwind?"
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
├── understand.py        # bullets + chapters (LLM if key present, else extractive)
├── library.py           # SQLite schema + CRUD + bundle export/import
├── mcp_server.py        # stdio MCP, 6 tools
├── youtube_history.py   # Google Takeout parser
├── deps.py              # `videomemory setup` wizard
├── embed.py             # bge-small wrapper
├── types.py             # Pydantic schemas
├── cli.py               # typer CLI
└── config.py            # env knobs
```

≈1k lines. read it in 20 minutes.

---

## v1.1 candidates (not yet in)

curious what you'd want most:

- 🎤 podcast RSS support
- 🌐 Loom / Twitch VOD / Vimeo
- 🧭 Chrome extension that auto-ingests as you watch
- 🔁 livestream / long-video segmented re-indexing
- 🎬 visual scene search (compute CLIP embeddings on frames)

open an issue with what you'd actually use.

---

## license

MIT. built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper) · [bge embeddings](https://huggingface.co/BAAI/bge-small-en-v1.5) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [MCP](https://modelcontextprotocol.io/) · [Anthropic Claude Code](https://claude.ai/code) · [OpenAI Codex](https://platform.openai.com/codex).

if this is useful, drop a ⭐ — that's the only thanks this project needs.
