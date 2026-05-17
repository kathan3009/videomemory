"""Qdrant-backed VectorStore. Supports both server-mode and local (file-backed) mode."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from videomemory.vector.base import VectorHit, VectorStore

log = logging.getLogger(__name__)


def _to_filter(filter: dict[str, Any] | None) -> qm.Filter | None:
    if not filter:
        return None
    must = []
    for k, v in filter.items():
        must.append(qm.FieldCondition(key=k, match=qm.MatchValue(value=v)))
    return qm.Filter(must=must)


class QdrantStore(VectorStore):
    """Qdrant client wrapper.

    Pass `url` for server mode (http://host:6333) or `path` for local mode.
    Local mode is great for tests / offline operation — no server required.
    """

    def __init__(self, url: str | None = None, path: Path | None = None) -> None:
        if path is not None:
            self.client = QdrantClient(path=str(path))
            self._mode = "local"
        else:
            self.client = QdrantClient(url=url or "http://localhost:6333")
            self._mode = "server"

    def ensure_collection(self, name: str, dim: int) -> None:
        try:
            self.client.get_collection(name)
            return
        except Exception:
            pass
        self.client.create_collection(
            collection_name=name,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )
        log.info("created qdrant collection %s dim=%d", name, dim)

    def collection_exists(self, name: str) -> bool:
        try:
            self.client.get_collection(name)
            return True
        except Exception:
            return False

    def upsert(
        self,
        name: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        if not ids:
            return
        points = [
            qm.PointStruct(id=_qdrant_id(i), vector=v, payload={**(p or {}), "__orig_id": i})
            for i, v, p in zip(ids, vectors, payloads, strict=True)
        ]
        self.client.upsert(collection_name=name, points=points, wait=True)

    def search(
        self,
        name: str,
        vector: list[float],
        top_k: int = 10,
        filter: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        try:
            res = self.client.query_points(
                collection_name=name,
                query=vector,
                limit=top_k,
                query_filter=_to_filter(filter),
                with_payload=True,
            ).points
        except Exception as exc:
            log.warning("qdrant search failed on %s: %s", name, exc)
            return []
        out: list[VectorHit] = []
        for p in res:
            payload = p.payload or {}
            out.append(
                VectorHit(
                    id=payload.get("__orig_id", str(p.id)),
                    score=float(p.score or 0.0),
                    payload=payload,
                )
            )
        return out

    def delete_collection(self, name: str) -> None:
        try:
            self.client.delete_collection(name)
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass

    def __enter__(self) -> QdrantStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _qdrant_id(orig: str) -> str | int:
    """Qdrant requires UUID or int ids. We accept either; otherwise hash to uuid."""
    import re
    import uuid

    if re.fullmatch(r"\d+", orig):
        return int(orig)
    try:
        return str(uuid.UUID(orig))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, orig))


def get_store(qdrant_url: str | None, local_path: Path | None) -> QdrantStore:
    if local_path:
        return QdrantStore(path=local_path)
    return QdrantStore(url=qdrant_url)
