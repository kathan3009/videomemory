"""Ollama LLM provider."""

from __future__ import annotations

import os

import httpx

from videomemory.query.providers.base import LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, model: str | None = None, url: str | None = None) -> None:
        self.url = (url or os.environ.get("VIDEOMEMORY_OLLAMA_URL") or "http://localhost:11434").rstrip("/")
        self.model = model or os.environ.get("VIDEOMEMORY_OLLAMA_MODEL") or "qwen2.5:3b"

    @classmethod
    def is_available(cls) -> bool:
        url = (os.environ.get("VIDEOMEMORY_OLLAMA_URL") or "http://localhost:11434").rstrip("/")
        try:
            r = httpx.get(f"{url}/api/tags", timeout=1.0)
            return r.status_code == 200
        except Exception:
            return False

    async def complete(self, system: str, user: str, max_tokens: int = 800) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{self.url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
        return (data.get("message", {}) or {}).get("content", "").strip()
