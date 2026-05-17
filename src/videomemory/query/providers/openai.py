"""OpenAI LLM provider (uses the Chat Completions endpoint via HTTP)."""

from __future__ import annotations

import os

import httpx

from videomemory.query.providers.base import LLMProvider


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or ""
        self.model = model or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"

    @classmethod
    def is_available(cls) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    async def complete(self, system: str, user: str, max_tokens: int = 800) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            r.raise_for_status()
            data = r.json()
        return data["choices"][0]["message"]["content"].strip()
