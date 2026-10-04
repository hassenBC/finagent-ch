"""retrieve(query, cfg): FTS and/or vector candidates -> RRF -> optional rerank -> top-k."""

from __future__ import annotations

from finagent.retrieval.expand import expand_query
from finagent.retrieval.fts import detect_ts_config, fts_search
from finagent.retrieval.fusion import rrf
from finagent.retrieval.metadata import extract_filters
from finagent.retrieval.rerank import rerank
from finagent.retrieval.types import Filters, Hit, RetrievalConfig
from finagent.retrieval.vector import vector_search


def retrieve(query: str, cfg: RetrievalConfig, filters: Filters | None = None) -> list[Hit]:
    if filters is None and cfg.use_metadata_filters:
        filters = extract_filters(query)
    fusion = cfg.fusion
    # when reranking, the candidate pool is whatever the first stage hands over
    pool_size = cfg.rerank.candidates if cfg.rerank.enabled else cfg.top_k

    queries = [query]
    if cfg.expansion.enabled:
        queries += expand_query(query, cfg.expansion.n, cfg.expansion.model)

    lists: list[list[Hit]] = []
    for q in queries:
        if cfg.retrieval in ("fts", "hybrid"):
            n = fusion.fts_candidates if cfg.retrieval == "hybrid" else max(pool_size, cfg.top_k)
            lists.append(fts_search(q, cfg.chunker, n, detect_ts_config(q), filters, cfg.fts))
        if cfg.retrieval in ("vector", "hybrid"):
            n = fusion.vector_candidates if cfg.retrieval == "hybrid" else max(pool_size, cfg.top_k)
            lists.append(
                vector_search(q, cfg.chunker, cfg.embedding_model, n, filters, ann=cfg.ann)
            )

    hits = rrf(lists, fusion.k) if len(lists) > 1 else lists[0]
    if cfg.rerank.enabled:
        return rerank(query, hits[: cfg.rerank.candidates], cfg.rerank.model, cfg.top_k)
    return hits[: cfg.top_k]
