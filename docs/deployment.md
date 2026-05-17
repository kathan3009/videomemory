# Deployment

## Local (recommended for dev)

```bash
uv sync --extra ml --extra dev
uv run python scripts/download_models.py
uv run videomemory ingest <path-or-url>
uv run videomemory mcp serve                # for Claude Desktop / Cursor / Windsurf / VSCode
uv run uvicorn videomemory.api.app:app --reload   # HTTP API
cd frontend && npm install && npm run dev   # web UI
```

## Docker

```bash
docker compose up -d
# API:      http://localhost:8000
# Frontend: http://localhost:3000
# Qdrant:   http://localhost:6333
```

The `vm_data` named volume persists ingested videos and artifacts across container restarts.

## Production notes

- Set `VIDEOMEMORY_QDRANT_IN_MEMORY=false` and point `VIDEOMEMORY_QDRANT_URL` at a managed Qdrant instance.
- For multi-user deployments, namespace data dirs per user (or use one Qdrant collection per `user_id__video_id`).
- The MCP server is single-tenant by design — run one per user, or use the FastAPI surface behind your auth.
- Model downloads happen on first use. Pre-pull via `scripts/download_models.py` in your image build (the included Dockerfile.api does this).

## Resource sizing

| Footprint | RAM | Disk (artifacts/h of video) |
|---|---:|---:|
| Light profile (default) | 2–4 GB | ~50 MB |
| Heavy (whisper-large + bge-large) | 6–10 GB | ~120 MB |

## Resumability

If an ingest is interrupted (e.g., process killed), simply re-run `videomemory ingest <same source>` — completed stages are detected via per-stage marker files under `<data>/videos/<video_id>/.stages/` and skipped.
