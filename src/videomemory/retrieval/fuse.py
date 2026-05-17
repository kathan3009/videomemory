"""Weighted Reciprocal Rank Fusion for multimodal retrieval scores."""

from __future__ import annotations

from collections.abc import Sequence


def rrf(
    ranked_lists: Sequence[Sequence[str]],
    weights: Sequence[float],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion across multiple ranked lists.

    Args:
        ranked_lists: each list is doc_ids ordered best-first.
        weights: weight per list; same length as `ranked_lists`.
        k: RRF constant.

    Returns:
        list[(doc_id, score)] sorted high-to-low.
    """
    if len(ranked_lists) != len(weights):
        raise ValueError("ranked_lists and weights length mismatch")
    scores: dict[str, float] = {}
    for ranks, w in zip(ranked_lists, weights, strict=True):
        for i, doc_id in enumerate(ranks):
            scores[doc_id] = scores.get(doc_id, 0.0) + w * (1.0 / (k + i + 1))
    return sorted(scores.items(), key=lambda kv: -kv[1])
