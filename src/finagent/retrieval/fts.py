"""Full-text search over chunks.tsv with an OR query ranked by cover density."""

from __future__ import annotations

import re

from finagent.db import pool
from finagent.ingest.text import normalise_numbers
from finagent.retrieval.sql import filter_sql
from finagent.retrieval.types import Filters, Hit


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_FR = _words(
    "le la les des du de un une et est sont pour au aux par sur dans que qui quel quelle "
    "quels quelles combien comment selon rapport montant exercice banque ont été avec ce "
    "cette ses leur"
)
_EN = _words(
    "the of and is are was were for in on by what which who how many much according report "
    "amount did does has have with this that its their"
)


def detect_ts_config(query: str) -> str:
    """Tiny language heuristic: French stop-words vs English ones."""
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", query.lower())
    fr, en = sum(w in _FR for w in words), sum(w in _EN for w in words)
    return "french" if fr > en else "english"


def fts_search(
    query: str, chunker: str, k: int, ts_config: str | None = None, filters: Filters | None = None
) -> list[Hit]:
    """Any-term match (plainto_tsquery with & turned into |), ranked by ts_rank_cd.

    websearch_to_tsquery ANDs every term, which returns nothing for a 20-word question.
    """
    cfg = ts_config or detect_ts_config(query)
    where, params = filter_sql(filters)
    sql = f"""
        WITH q AS (
            SELECT replace(
                plainto_tsquery(%(cfg)s::regconfig, %(q)s)::text, ' & ', ' | '
            )::tsquery AS tsq
        )
        SELECT c.chunk_id, c.doc_id, c.page_start, c.page_end, c.content,
               ts_rank_cd(c.tsv, q.tsq) AS score
        FROM chunks c JOIN documents d USING (doc_id), q
        WHERE c.chunker = %(chunker)s AND c.tsv @@ q.tsq {where}
        ORDER BY score DESC, c.chunk_id LIMIT %(k)s"""
    with pool().connection() as conn:
        rows = conn.execute(
            sql, {"cfg": cfg, "q": normalise_numbers(query), "chunker": chunker, "k": k, **params}
        ).fetchall()
    return [
        Hit(
            chunk_id=r[0],
            doc_id=r[1],
            page_start=r[2],
            page_end=r[3],
            content=r[4],
            score=float(r[5]),
            source="fts",
        )
        for r in rows
    ]
