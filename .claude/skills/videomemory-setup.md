---
name: videomemory-setup
description: One-shot installer for the videomemory repo. Invoke this when the user clones the repo and asks Claude/Codex to "set this up", "install it", "wire it into Claude Code", or similar.
---

# videomemory · setup

Goal: leave the user with a working `videomemory` MCP server registered in their Claude Code (or Codex) config, ready to use on YouTube URLs and local videos.

## What to do

Run `./setup.sh --yes` from the repo root.

```bash
./setup.sh --yes
```

That script (idempotent, safe to re-run) handles everything:

1. Installs `ffmpeg` + `yt-dlp` via brew (macOS) or apt (Linux) if missing.
2. Installs `uv` if missing.
3. Runs `uv sync` to install Python deps.
4. Runs `uv run videomemory setup` to pre-pull the two ML models (~600 MB, faster-whisper + bge-small).
5. Registers the MCP server with Claude Code at **user scope** so every future Claude Code session can use it.

If the user is on **Codex** (or any MCP client that isn't Claude Code), skip step 5's auto-registration and instead tell them to paste this into their MCP config:

```json
{
  "mcpServers": {
    "videomemory": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "<absolute path to this repo>",
        "videomemory",
        "mcp",
        "serve"
      ]
    }
  }
}
```

(Use `$(pwd)` from the repo root for the absolute path.)

## After setup, verify

Don't just say "done." Confirm it works:

```bash
claude mcp list 2>&1 | grep videomemory
```

That line should contain `✓ Connected`. If it doesn't, debug before reporting success.

## Suggest a first prompt

End by suggesting the user open a **new** Claude Code session and try this exact prompt:

> "use videomemory to skip to the part of https://youtu.be/BM70fDqUo3c where they explain the main idea"

The user has to start a new Claude Code session for the new MCP server to be picked up — current sessions won't see it.

## Tools the user will get

After setup, Claude/Codex can call these MCP tools:

| Tool | When to use |
|---|---|
| `skip(url, question)` | Find the exact timestamp answering `question` in a video. |
| `frames(url, count\|every\|at)` | Sample N keyframes — for visual videos with little/no audio. |
| `understand(url)` | Summary + chapter timestamps + transcript. |
| `search(query)` | Cross-video search across the user's library. |
| `add(url)` | Add a video to the library without asking a question. |
| `list()` | Show all videos in the library. |

## Watch out for

- **Don't run the setup more than once in a row** — it takes ~2 min on first run but the second time is nearly instant; just say "already set up."
- **Don't try to use the MCP from the current session** — only a fresh `claude` session will see the newly-registered server.
- **Don't deploy anything** — videomemory v0.2 is local-only by design. There's no Docker, no Fly, no hosted demo to set up.
- **Default data dir** is `~/.videomemory/` — the user's library lives there. Don't change it without asking.
