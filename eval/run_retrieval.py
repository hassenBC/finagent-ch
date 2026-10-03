"""Run retrieval configs on a QA dataset and store per-question metrics in Postgres.

python -m eval.run_retrieval configs/retrieval/A_table_aware_hybrid.yaml [...]
python -m eval.run_retrieval --grid 'configs/retrieval/A_*.yaml'
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import time
import uuid

from psycopg.types.json import Jsonb

from eval.metrics import (
    is_relevant,
    ndcg_at_k,
    page_coverage,
    percentile,
    recall_at_k,
    reciprocal_rank,
)
from finagent.config import ROOT
from finagent.db import pool
from finagent.retrieval.pipeline import retrieve
from finagent.retrieval.types import RetrievalConfig

KS = (1, 3, 5, 10)


def load_items(path: str) -> list[dict]:
    rows = [json.loads(ln) for ln in (ROOT / path).read_text().splitlines()]
    return [r for r in rows if r["answerable"]]  # unanswerable items are excluded from retrieval


def sha_to_doc() -> dict[str, int]:
    with pool().connection() as conn:
        return dict(conn.execute("SELECT sha256, doc_id FROM documents").fetchall())


def gold_pages(item: dict, docs: dict[str, int]) -> tuple[set, set]:
    """(primary gold pages, gold + alternate pages), as (doc_id, page) pairs."""
    primary = {(docs[g["sha256"]], g["page"]) for g in item["gold_pages"]}
    relevant = primary | {(docs[g["sha256"]], g["page"]) for g in item.get("alt_pages", [])}
    return primary, relevant


def n_relevant_chunks(chunker: str, pages: set) -> int:
    docs, nums = [d for d, _ in pages], [p for _, p in pages]
    with pool().connection() as conn:
        return conn.execute(
            """SELECT count(DISTINCT c.chunk_id) FROM chunks c
               JOIN unnest(%s::int[], %s::int[]) AS g(doc_id, page)
                 ON c.doc_id = g.doc_id AND g.page BETWEEN c.page_start AND c.page_end
               WHERE c.chunker = %s""",
            (docs, nums, chunker),
        ).fetchone()[0]


def git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()


def run_config(cfg: RetrievalConfig, store: bool = True) -> dict:
    items = load_items(cfg.dataset)
    docs = sha_to_doc()
    retrieve(items[0]["question"], cfg)  # warm-up: model loading is excluded from latency
    results = []
    for item in items:
        primary, relevant = gold_pages(item, docs)
        t0 = time.perf_counter()
        hits = retrieve(item["question"], cfg)
        latency_ms = (time.perf_counter() - t0) * 1000
        rel = [is_relevant(h, relevant) for h in hits]
        n_rel = n_relevant_chunks(cfg.chunker, relevant)
        metrics = {f"recall@{k}": recall_at_k(rel, k) for k in KS}
        metrics.update(
            {
                "mrr@10": reciprocal_rank(rel, 10),
                "ndcg@10": ndcg_at_k(rel, 10, n_rel),
                "page_cov@10": page_coverage(hits, primary, 10),
                "latency_ms": latency_ms,
                "n_relevant_chunks": n_rel,
            }
        )
        output = {
            "type": item["type"],
            "lang": item["lang"],
            "hits": [
                {
                    "chunk_id": h.chunk_id,
                    "doc_id": h.doc_id,
                    "pages": [h.page_start, h.page_end],
                    "score": round(h.score, 5),
                    "relevant": r,
                }
                for h, r in zip(hits, rel, strict=True)
            ],
        }
        results.append((item["id"], metrics, output))

    run_id = uuid.uuid4()
    if store:
        with pool().connection() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO eval_runs (run_id, kind, config, git_sha, dataset) "
                "VALUES (%s, 'retrieval', %s, %s, %s)",
                (run_id, Jsonb(cfg.model_dump()), git_sha(), cfg.dataset),
            )
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO eval_results (run_id, item_id, metrics, output) "
                    "VALUES (%s, %s, %s, %s)",
                    [(run_id, i, Jsonb(m), Jsonb(o)) for i, m, o in results],
                )
    lat = [m["latency_ms"] for _, m, _ in results]
    mean = lambda key: sum(m[key] for _, m, _ in results) / len(results)  # noqa: E731
    print(
        f"{cfg.name:34} n={len(results)} R@1={mean('recall@1'):.3f} R@5={mean('recall@5'):.3f} "
        f"R@10={mean('recall@10'):.3f} MRR={mean('mrr@10'):.3f} nDCG={mean('ndcg@10'):.3f} "
        f"p50={percentile(lat, 50):.0f}ms p95={percentile(lat, 95):.0f}ms",
        flush=True,
    )
    return {"run_id": run_id, "results": results}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="*")
    ap.add_argument("--grid", help="glob of config files")
    ap.add_argument("--no-store", action="store_true")
    args = ap.parse_args()
    paths = sorted(args.configs + (glob.glob(args.grid) if args.grid else []))
    for p in paths:
        run_config(RetrievalConfig.from_yaml(p), store=not args.no_store)


if __name__ == "__main__":
    main()
