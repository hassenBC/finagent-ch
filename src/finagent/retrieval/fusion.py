"""Reciprocal rank fusion."""

from __future__ import annotations

from finagent.retrieval.types import Hit


def rrf(rankings: list[list[Hit]], k: int = 60) -> list[Hit]:
    """score(d) = sum_i 1 / (k + rank_i(d)), ranks starting at 1."""
    scores: dict[int, float] = {}
    first: dict[int, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, 1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            first.setdefault(hit.chunk_id, hit)
    fused = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [
        first[cid].model_copy(update={"score": scores[cid], "source": "fused"}) for cid in fused
    ]
