"""Embed chunks with sentence-transformers and store them in one emb_<model> table each."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from finagent.db import pool

# key -> (hf model, dimension, passage prefix, query prefix)
EMBEDDERS = {
    "e5_small": ("intfloat/multilingual-e5-small", 384, "passage: ", "query: "),
    "e5_large": ("intfloat/multilingual-e5-large", 1024, "passage: ", "query: "),
    "bge_m3": ("BAAI/bge-m3", 1024, "", ""),
}


@lru_cache
def _model(model_key: str):
    import torch
    from sentence_transformers import SentenceTransformer

    name = EMBEDDERS[model_key][0]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    m = SentenceTransformer(name, device=device)
    if device == "cuda":
        m.half()  # 4 GB laptop GPU
    m.max_seq_length = 512
    return m


def _encode(model_key: str, texts: list[str], prefix: str, batch_size: int) -> np.ndarray:
    vecs = _model(model_key).encode(
        [prefix + t for t in texts],
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return vecs.astype(np.float32)


def embed_query(model_key: str, text: str) -> np.ndarray:
    return _encode(model_key, [text], EMBEDDERS[model_key][3], 1)[0]


def embed_chunks(model_key: str, chunker: str, batch_size: int = 32, commit_every: int = 2048):
    """Embed every chunk of `chunker` that has no embedding yet (resumable)."""
    _, dim, passage_prefix, _ = EMBEDDERS[model_key]
    table = f"emb_{model_key}"
    with pool().connection() as conn:
        conn.execute(
            f"""CREATE TABLE IF NOT EXISTS {table} (
                    chunk_id  BIGINT PRIMARY KEY REFERENCES chunks ON DELETE CASCADE,
                    embedding VECTOR({dim}) NOT NULL)"""
        )
        todo = conn.execute(
            f"""SELECT c.chunk_id, c.content FROM chunks c
                LEFT JOIN {table} e USING (chunk_id)
                WHERE c.chunker = %s AND e.chunk_id IS NULL ORDER BY c.chunk_id""",
            (chunker,),
        ).fetchall()
        print(f"{table} / {chunker}: {len(todo)} chunks to embed", flush=True)
        for i in range(0, len(todo), commit_every):
            part = todo[i : i + commit_every]
            vecs = _encode(model_key, [t for _, t in part], passage_prefix, batch_size)
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {table} (chunk_id, embedding) VALUES (%s, %s)",
                    [(cid, v) for (cid, _), v in zip(part, vecs, strict=True)],
                )
            conn.commit()
            print(f"  {i + len(part)}/{len(todo)}", flush=True)
        # build the index after the bulk insert (faster)
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_hnsw ON {table} "
            "USING hnsw (embedding vector_cosine_ops)"
        )
        conn.commit()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("model", choices=list(EMBEDDERS))
    ap.add_argument("chunkers", nargs="*", default=["fixed512", "structure", "table_aware"])
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()
    for chunker in args.chunkers:
        embed_chunks(args.model, chunker, batch_size=args.batch)
