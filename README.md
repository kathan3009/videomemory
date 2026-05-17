# VideoMemory

> A **video memory operating system** for AI agents. Turns videos into semantic temporal memory that agents query through MCP — no more dumping frames into prompts.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)

VideoMemory ingests a video once, builds a **scene graph + event log + temporal edges + multimodal embeddings**, indexes everything in a vector store, and exposes it to LLMs through the **Model Context Protocol (MCP)**. The agent retrieves only the chunks and frames it actually needs — temporal queries like *"what happened after the OAuth discussion?"* resolve to a small set of semantic chunks plus 1–8 keyframes, never the whole video.

This is **not** a transcript wrapper, a captioning tool, or another RAG demo. It's an infrastructure layer for agents that need to reason over video.

## What you can do

- `videomemory ingest sample.mp4` — full pipeline (scenes → audio → vision → memory → index)
- `videomemory ingest https://youtu.be/...` — same, with `yt-dlp`
- `videomemory ask <video_id> "what happened after the argument started?"` — temporal query
- `videomemory frames search <video_id> --query whiteboard` — selective frame recall
- `videomemory mcp serve` — expose 7 tools over stdio to Claude Desktop / Cursor / Windsurf / VSCode / any MCP client
- `docker compose up` — full stack (Qdrant + API + frontend + MCP)

## Quickstart

```bash
git clone https://github.com/kathan3009/videomemory.git
cd videomemory
uv sync --extra ml --extra dev
uv run python scripts/download_models.py
uv run videomemory ingest tests/fixtures/data/tech_talk.mp4
uv run videomemory ask <video_id> "When was Kubernetes discussed?"
```

Connect Claude Desktop by adding the snippet in `examples/claude_desktop_config.json` to your Claude Desktop config — then ask Claude about your video directly.

## Architecture

```
video → ingest → decompose → audio + vision → temporal memory
                                                    ↓
                              semantic chunks ← scene graph
                                    ↓
                              bge-small embeddings → Qdrant
                                    ↓
                              retrieval router (temporal / OCR / visual / semantic / fuse)
                                    ↓
                              MCP server  →  AI agent
```

See [docs/architecture.md](docs/architecture.md) for the full design.

## Light, MPS-friendly model profile

VideoMemory runs **offline** on Apple Silicon (M-series) and modest CPUs:

| Component | Model | Notes |
|---|---|---|
| Transcription | faster-whisper `small` | CTranslate2, CPU + MPS |
| Vision tags / image embeddings | CLIP ViT-B/32 (open-clip) | MPS or CPU |
| OCR | rapidocr-onnxruntime | ONNX, ARM-clean |
| Detection (optional) | YOLOv8n | Skippable |
| Text embeddings | bge-small-en-v1.5 | ~100 MB |
| Vector store | Qdrant | Local or Docker |
| Captions | object + OCR + scene tag template (default) or local Ollama VLM | No cloud required |
| Diarization (optional) | pyannote-audio | Requires HF token; off by default |

Heavier model swaps are pluggable via config; see [docs/models.md](docs/models.md).

## MCP tools

| Tool | Purpose |
|---|---|
| `ingest_video` | Ingest a path or URL, get a job ID |
| `list_videos` | Inventory of ingested videos |
| `query_video` | One-shot Q&A with chunks + selective frames |
| `get_timeline` | Scene / chunk / event timeline |
| `get_frames` | Up to N relevant frames for a query |
| `semantic_search` | Multimodal retrieval (transcript / OCR / visual / fused) |
| `get_transcript` | Filtered transcript by speaker / time |

Token-budgeted responses. Frames are returned as MCP **resource URIs** (`videomemory://...`), not base64 blobs — Claude fetches on demand.

## Design choices (deviations from a naive build)

- `uv` for env + lock (10–100× faster than pip).
- Qdrant only in v1; `VectorStore` interface keeps LanceDB pluggable.
- `rapidocr-onnxruntime` instead of PaddleOCR (Apple Silicon stability).
- CLIP + templated captions instead of heavyweight VLMs by default.
- bge-small instead of bge-large (90% of accuracy for a fraction of footprint).
- pyannote diarization is opt-in.
- Stdio MCP transport first (what every real client uses today).
- Async + on-disk stage cache for resumability; no Celery/Airflow needed.

See the deviations table in the architecture doc for the full reasoning.

## Status

Alpha. The 15 acceptance tests in `tests/integration/` cover ingestion, temporal retrieval, frame recall, OCR queries, multimodal fusion, MCP tool surface, long-video scaling, and resumability. See [`docs/architecture.md`](docs/architecture.md) and [`docs/mcp.md`](docs/mcp.md) for details.

## License

MIT — see [LICENSE](LICENSE).
