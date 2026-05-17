# Dockerfile — for hosting example.com on Fly.io.
# Local users don't need this — they install via `claude mcp add ... uv run videomemory mcp serve`.
#
# This image only ships the HTTP server (`videomemory.server:app`) which exposes:
#   - GET  /            single-page demo
#   - POST /skip /search /understand /add
#   - POST /mcp         HTTP MCP transport for remote installs
#
# Stays small by pre-pulling models in the build stage and discarding build deps.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/opt/hf

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev

# Warm caches so first request is fast
COPY scripts/ ./scripts/
RUN uv run python scripts/download_models.py || true


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIDEOMEMORY_DATA_DIR=/data \
    HF_HOME=/opt/hf

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg yt-dlp ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app /app
COPY --from=builder /opt/hf /opt/hf

VOLUME ["/data"]
EXPOSE 8000

CMD ["/app/.venv/bin/uvicorn", "videomemory.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
