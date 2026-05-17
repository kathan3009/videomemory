<div align="center">

# 🎬 videomemory

### the video understanding layer for **Claude Code** & **Codex**

paste any YouTube link → ask anything about it. **MCP-native.** Works in any agent.

[![MIT](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab.svg)](https://www.python.org/)
[![Demo](https://img.shields.io/badge/demo-example.com-34d399.svg)](https://example.com)
[![Stars](https://img.shields.io/github/stars/kathan3009/videomemory?style=social)](https://github.com/kathan3009/videomemory)

</div>

---

```
you  ▸  "ingest https://youtu.be/BM70fDqUo3c. where do they configure tailwind?"

claude ▸  Calling videomemory.skip()...
       ▸  14:23  →  https://youtu.be/BM70fDqUo3c?t=863
       ▸  "First, we install Tailwind by running npm install tailwindcss..."
```

That's the whole pitch. Three things make it stick:

| | feature | what it does |
|---|---|---|
| ⚡ | **Skip**            | Paste a URL + a question. Get the timestamp + deep link + frame + transcript excerpt. Done. |
| 📚 | **Watch History**   | Import your Google Takeout YouTube history. Your agent can now search **everything you've ever watched.** |
| 👯 | **Watch Club**      | Export your library as a single file. Hand it to a friend. They `import` it. Now their agent knows what you know. |

---

## install in 30 seconds

### option 1 — hosted (zero setup)

Use the public instance. No Python, no models to download. Same MCP surface.

```bash
claude mcp add -s user videomemory \
  https://example.com/mcp \
  --transport http
```

For **Codex** (or any MCP client), add to your config:

```json
{
  "mcpServers": {
    "videomemory": {
      "url": "https://example.com/mcp",
      "transport": "http"
    }
  }
}
```

That's it. Restart your agent and ask it to *"skip to the part of this video where..."*.

### option 2 — local (private, no rate limits)

```bash
git clone https://github.com/kathan3009/videomemory.git
cd videomemory
uv run videomemory setup        # checks ffmpeg/yt-dlp, pre-pulls models, prints install line
```

`setup` ends by printing the exact `claude mcp add` line for your machine. Paste it. Done.

---

## the 5 MCP tools

| tool | what it does |
|---|---|
| `understand(url)` | Watch a video. Returns title + duration + 4–8 bullet takeaways + chapter timestamps + transcript. |
| `skip(url, q)`    | Find the exact moment that answers `q`. Returns timestamp, deep link, frame, excerpt. |
| `search(query)`   | Search across **every video in your library**. Cross-video retrieval. |
| `add(url)`        | Ingest a video into your library without asking a question. |
| `list()`          | Show what's in your library. |

Frames are returned as `videomemory://frames/<video_id>/<file>` resource URIs so the agent only fetches them on demand — no context-blowing base64 blobs.

---

## use it from the terminal too

```bash
# Skip to the answer in any video
videomemory skip https://youtu.be/BM70fDqUo3c "what is this about?"

# Search across everything you've watched
videomemory search "Postgres index tuning"

# Import your YouTube history
videomemory history ~/Downloads/Takeout/YouTube*/history/watch-history.json --limit 200

# Share your library with a friend (Watch Club)
videomemory export my-library.sqlite
# they run:
videomemory import my-library.sqlite
```

---

## how it works

```
URL  ──▸  yt-dlp ──▸  ffmpeg ──▸  faster-whisper ──▸  30s windows
                                                          │
                                                          ▼
                                        bge-small-en-v1.5 embeddings
                                                          │
                                                          ▼
                                                   SQLite library
                                                          │
                                                          ▼
                          ┌───────────────────┬───────────┴──────────┐
                          ▼                   ▼                      ▼
                       skip()             search()              understand()
                          │                   │                      │
                          └──── cosine over cached vectors ──────────┘
                                              │
                                              ▼
                                          MCP tools
                                              │
                            ┌─────────────────┼──────────────────┐
                            ▼                 ▼                  ▼
                       Claude Code         Codex            any MCP client
```

**Light by design.** No Qdrant. No CLIP. No OCR. No frontend. No object detection. No memory graph. Just transcription + a single embedding model + cosine + SQLite. The smart layer is the agent — we just give it eyes and a library.

| | dep | size | why |
|---|---|---:|---|
| 🔊 | faster-whisper (small) | ~470 MB | transcription |
| 🧠 | bge-small-en-v1.5 | ~120 MB | text embeddings |
| 🎬 | ffmpeg + yt-dlp | tiny | source + frames |
| 🗄️ | sqlite | – | library + vectors |

Pre-pulled in one command (`videomemory setup`). Runs **fully offline** after first install.

---

## what's *not* in v1 (yet)

Saved for v1.1 — feedback welcome.

- OCR queries on slides / screen text
- Visual search ("find the frame with the whiteboard")
- Cross-video temporal reasoning
- Chrome extension auto-ingest while you browse
- Loom / Twitch VOD / TikTok / podcast-RSS sources
- Long videos > 1 hour (cap is configurable but tested up to 1 h)

---

## development

```bash
uv sync --extra dev
uv run pytest -q                 # 28 tests, ~40s
uv run ruff check .
```

To deploy to your own hosted endpoint:

```bash
flyctl launch --copy-config --no-deploy
flyctl deploy
flyctl certs add example.com
```

See [`docs/deploy-prod.md`](docs/deploy-prod.md).

---

## license

MIT. Built with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [bge embeddings](https://huggingface.co/BAAI/bge-small-en-v1.5), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [MCP](https://modelcontextprotocol.io/).

If this is useful, drop a ⭐ — that's the only "thanks" the project needs.
