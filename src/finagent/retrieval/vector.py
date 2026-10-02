"""Dense retrieval with pgvector (cosine distance)."""

from __future__ import annotations

from finagent.db import pool
from finagent.ingest.embed import embed_query
from finagent.retrieval.sql import filter_sql
from finagent.retrieval.types import Filters, Hit


def vector_search(
    query: str,
    chunker: str,
    model_key: str,
    k: int,
    filters: Filters | None = None,
    ann: bool = True,
) -> list[Hit]:
    qvec = embed_query(model_key, query)
    where, params = filter_sql(filters)
    table = f"emb_{model_key}"
    sql = f"""
        SELECT c.chunk_id, c.doc_id, c.page_start, c.page_end, c.content,
               1 - (e.embedding <=> %(v)s) AS score
        FROM {table} e JOIN chunks c USING (chunk_id) JOIN documents d USING (doc_id)
        WHERE c.chunker = %(chunker)s {where}
        ORDER BY e.embedding <=> %(v)s LIMIT %(k)s"""
    with pool().connection() as conn, conn.transaction():
        if ann:
            conn.execute("SET LOCAL hnsw.ef_search = 100")
            conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")  # filters post-scan
        else:
            conn.execute("SET LOCAL enable_indexscan = off")  # exact scan
        rows = conn.execute(sql, {"v": qvec, "chunker": chunker, "k": k, **params}).fetchall()
    return [
        Hit(
            chunk_id=r[0],
            doc_id=r[1],
            page_start=r[2],
            page_end=r[3],
            content=r[4],
            score=float(r[5]),
            source="vector",
        )
        for r in rows
    ]
