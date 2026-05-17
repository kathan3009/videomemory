"""LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def complete(self, system: str, user: str, max_tokens: int = 800) -> str: ...

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool: ...
