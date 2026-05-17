"""Abstract VectorStore interface used by retrieval and indexing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class VectorHit:
    id: str
    score: float
    payload: dict[str, Any]


class VectorStore(ABC):
    @abstractmethod
    def ensure_collection(self, name: str, dim: int) -> None: ...

    @abstractmethod
    def upsert(
        self,
        name: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None: ...

    @abstractmethod
    def search(
        self,
        name: str,
        vector: list[float],
        top_k: int = 10,
        filter: dict[str, Any] | None = None,
    ) -> list[VectorHit]: ...

    @abstractmethod
    def delete_collection(self, name: str) -> None: ...

    @abstractmethod
    def collection_exists(self, name: str) -> bool: ...
