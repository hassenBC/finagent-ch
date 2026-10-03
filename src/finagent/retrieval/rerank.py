"""Cross-encoder reranking."""

from __future__ import annotations

from functools import lru_cache

from finagent.retrieval.types import Hit


@lru_cache
def _model(name: str):
    import torch
    from sentence_transformers import CrossEncoder

    device = "cuda" if torch.cuda.is_available() else "cpu"
    m = CrossEncoder(name, device=device, max_length=512)
    if device == "cuda":
        m.model.half()
    return m


def rerank(query: str, hits: list[Hit], model: str, top_k: int, batch_size: int = 16) -> list[Hit]:
    if not hits:
        return []
    scores = _model(model).predict(
        [(query, h.content) for h in hits], batch_size=batch_size, show_progress_bar=False
    )
    order = sorted(range(len(hits)), key=lambda i: -float(scores[i]))[:top_k]
    return [
        hits[i].model_copy(update={"score": float(scores[i]), "source": "rerank"}) for i in order
    ]
