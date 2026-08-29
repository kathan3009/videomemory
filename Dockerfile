FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/data/models/huggingface \
    TORCH_HOME=/data/models/torch \
    XDG_CACHE_HOME=/data/models/cache \
    VIDEOMEMORY_HOSTED=1 \
    VIDEOMEMORY_DATA_ROOT=/data/videomemory

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.11

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev

RUN mkdir -p /data/videomemory /data/models
EXPOSE 8080

CMD ["sh", "-c", "videomemory mcp serve-http --host 0.0.0.0 --port ${PORT:-8080}"]
