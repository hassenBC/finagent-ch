"""Full-text search over chunks.tsv with an OR query ranked by cover density."""

from __future__ import annotations

import re
from functools import lru_cache

from finagent.db import pool
from finagent.ingest.text import normalise_numbers
from finagent.retrieval.sql import filter_sql
from finagent.retrieval.types import Filters, FTSOptions, Hit


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


@lru_cache(maxsize=16)
def _doc_freq(chunker: str) -> tuple[dict[str, int], int]:
    """Lexeme -> number of chunks containing it, for one chunker (Postgres has no IDF)."""
    with pool().connection() as conn:
        n = conn.execute("SELECT count(*) FROM chunks WHERE chunker = %s", (chunker,)).fetchone()[0]
        inner = f"SELECT tsv FROM chunks WHERE chunker = '{chunker}'"  # chunker is a config literal
        rows = conn.execute("SELECT word, ndoc FROM ts_stat(%s)", (inner,)).fetchall()
    return dict(rows), n


def _query_lexemes(query: str, cfg: str) -> list[str]:
    with pool().connection() as conn:
        row = conn.execute(
            "SELECT tsvector_to_array(to_tsvector(%s::regconfig, %s))", (cfg, query)
        ).fetchone()
    return list(row[0] or [])


def build_tsquery(query: str, cfg: str, chunker: str, max_df: float | None) -> str:
    """OR of the query's lexemes, optionally without terms that occur in most chunks."""
    lexemes = _query_lexemes(query, cfg)
    if max_df is not None:
        df, n = _doc_freq(chunker)
        kept = [lx for lx in lexemes if df.get(lx, 0) <= max_df * n]
        lexemes = kept or lexemes  # never send an empty query
    return " | ".join("'" + lx.replace("'", "''") + "'" for lx in lexemes)


def fts_search(
    query: str,
    chunker: str,
    k: int,
    ts_config: str | None = None,
    filters: Filters | None = None,
    options: FTSOptions | None = None,
) -> list[Hit]:
    """Any-term match ranked by ts_rank_cd (or ts_rank), optionally pruning common terms.

    websearch_to_tsquery ANDs every term, which returns nothing for a 20-word question.
    """
    opt = options or FTSOptions()
    cfg = ts_config or detect_ts_config(query)
    tsq = build_tsquery(normalise_numbers(query), cfg, chunker, opt.max_df)
    if not tsq:
        return []
    rank_fn = "ts_rank_cd" if opt.rank == "cd" else "ts_rank"
    where, params = filter_sql(filters)
    sql = f"""
        SELECT c.chunk_id, c.doc_id, c.page_start, c.page_end, c.content,
               {rank_fn}(c.tsv, q.tsq, %(norm)s) AS score
        FROM chunks c JOIN documents d USING (doc_id),
             (SELECT %(tsq)s::tsquery AS tsq) q
        WHERE c.chunker = %(chunker)s AND c.tsv @@ q.tsq {where}
        ORDER BY score DESC, c.chunk_id LIMIT %(k)s"""
    with pool().connection() as conn:
        rows = conn.execute(
            sql, {"tsq": tsq, "norm": opt.normalization, "chunker": chunker, "k": k, **params}
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
