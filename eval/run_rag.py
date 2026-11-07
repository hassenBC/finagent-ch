"""Run retrieval + answer generation on a QA dataset and store per-question metrics.

python -m eval.run_rag configs/rag/<name>.yaml [...] [--dataset ...] [--max-cost 0.5]
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import yaml
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from eval.metrics import percentile
from eval.rag_metrics import abstention_scores, citation_scores, numeric_match
from eval.run_retrieval import git_sha, gold_pages, sha_to_doc
from finagent.config import ROOT
from finagent.db import pool
from finagent.llm.client import LLMClient
from finagent.rag.answer import answer
from finagent.retrieval.pipeline import retrieve
from finagent.retrieval.types import RetrievalConfig


class RagConfig(BaseModel):
    name: str
    retrieval: str  # path to a retrieval YAML
    k: int = 5  # chunks given to the generator
    generator: str = "deepseek_flash"
    dataset: str = "eval/datasets/qa_dev.jsonl"


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, cap: float) -> None:
        self.cap, self.spent, self.lock = cap, 0.0, threading.Lock()

    def charge(self, usd: float) -> None:
        with self.lock:
            self.spent += usd

    def check(self) -> None:
        if self.spent >= self.cap:
            raise BudgetExceeded(f"cost cap ${self.cap:.2f} reached (${self.spent:.3f} spent)")


def page_texts() -> dict[tuple[int, int], str]:
    with pool().connection() as conn:
        return {(d, p): t for d, p, t in conn.execute("SELECT doc_id, page_no, text FROM pages")}


def run(cfg: RagConfig, budget: Budget, workers: int = 6) -> None:
    items = [json.loads(ln) for ln in (ROOT / cfg.dataset).read_text().splitlines()]
    rcfg = RetrievalConfig.from_yaml(cfg.retrieval)
    rcfg = rcfg.model_copy(update={"top_k": max(rcfg.top_k, cfg.k)})
    docs, texts = sha_to_doc(), page_texts()
    llm = LLMClient.from_config(cfg.generator)

    retrieve(items[0]["question"], rcfg)  # warm-up
    hits_of, rlat = {}, {}
    for it in items:
        t0 = time.perf_counter()
        hits_of[it["id"]] = retrieve(it["question"], rcfg)[: cfg.k]
        rlat[it["id"]] = (time.perf_counter() - t0) * 1000

    def gen(it):
        budget.check()
        r = answer(it["question"], hits_of[it["id"]], llm)
        budget.charge(r.cost_usd)
        return it, r

    results = []
    with ThreadPoolExecutor(workers) as ex:
        for fut in [ex.submit(gen, it) for it in items]:
            try:
                results.append(fut.result())
            except BudgetExceeded as e:
                print(f"STOP: {e}", flush=True)
                break
            except Exception as e:  # one bad generation must not kill the run
                print(f"generation failed: {repr(e)[:120]}", flush=True)
    if len(results) < len(items):
        print(f"incomplete run ({len(results)}/{len(items)}); not stored", flush=True)
        return

    rows = []
    for it, r in results:
        m: dict = {
            "abstain": float(r.abstain),
            "answerable": float(it["answerable"]),
            "n_citations": len(r.citations),
            "n_invalid_citations": len(r.invalid_citations),
            "retrieval_ms": rlat[it["id"]],
            "generation_ms": r.latency_ms,
            "cached": float(r.cached),
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "cost_usd": r.cost_usd,
            "generation_error": float(r.generation_error),
        }
        if it["answerable"]:
            _, relevant = gold_pages(it, docs)
            ok = citation_scores(
                [(c.doc_id, c.page_start, c.page_end) for c in r.citations],
                relevant,
                texts,
                it["evidence"],
            )
            m["n_correct_citations"] = sum(ok)
            m["has_correct_citation"] = float(any(ok))
            if it["answer_numeric"]:
                m.update(numeric_match(r.answer, it["answer_numeric"]))
        out = {"type": it["type"], "lang": it["lang"], "answer": r.answer,
               "citations": [c.model_dump() for c in r.citations],
               "invalid_citations": r.invalid_citations}  # fmt: skip
        rows.append((it["id"], m, out))

    run_id = uuid.uuid4()
    with pool().connection() as conn, conn.transaction():
        conn.execute(
            "INSERT INTO eval_runs (run_id, kind, config, git_sha, dataset) "
            "VALUES (%s, 'rag', %s, %s, %s)",
            (
                run_id,
                Jsonb({**cfg.model_dump(), "retrieval_config": rcfg.model_dump()}),
                git_sha(),
                cfg.dataset,
            ),  # fmt: skip
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO eval_results (run_id, item_id, metrics, output) "
                "VALUES (%s, %s, %s, %s)",
                [(run_id, i, Jsonb(m), Jsonb(o)) for i, m, o in rows],
            )
    print(summary_line(cfg.name, [m for _, m, _ in rows]), flush=True)


def summarise(ms: list[dict]) -> dict:
    ans = [m for m in ms if m["answerable"]]
    num = [m for m in ans if "em_any" in m]
    cites = sum(m["n_citations"] for m in ans)
    lat = [m["retrieval_ms"] + m["generation_ms"] for m in ms if not m["cached"]]
    s = {
        "n": len(ms),
        "numeric_em": sum(m["em_any"] for m in num) / len(num) if num else float("nan"),
        "numeric_em_first": sum(m["em_first"] for m in num) / len(num) if num else float("nan"),
        "citation_precision": sum(m["n_correct_citations"] for m in ans) / cites if cites else 0.0,
        "citation_recall": sum(m["has_correct_citation"] for m in ans) / len(ans),
        "invalid_citation_rate": sum(m["n_invalid_citations"] for m in ms)
        / max(1, sum(m["n_citations"] + m["n_invalid_citations"] for m in ms)),
        **abstention_scores([{"answerable": m["answerable"], "abstain": m["abstain"]} for m in ms]),
        "latency_p50_ms": percentile(lat, 50) if lat else float("nan"),
        "latency_p95_ms": percentile(lat, 95) if lat else float("nan"),
        "cost_per_query_usd": sum(m["cost_usd"] for m in ms) / len(ms),
        "generation_errors": sum(m.get("generation_error", 0.0) for m in ms),
    }
    return s


def summary_line(name: str, ms: list[dict]) -> str:
    s = summarise(ms)
    return (
        f"{name:28} n={s['n']} EM={s['numeric_em']:.3f} citeP={s['citation_precision']:.3f} "
        f"citeR={s['citation_recall']:.3f} invalid={s['invalid_citation_rate']:.3f} "
        f"abstF1={s['abstain_f1']:.2f} falseAbst={s['false_abstention_rate']:.3f} "
        f"p50={s['latency_p50_ms']:.0f}ms cost/q=${s['cost_per_query_usd']:.5f}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="+")
    ap.add_argument("--dataset")
    ap.add_argument("--max-cost", type=float, default=0.5, help="USD cap for this invocation")
    args = ap.parse_args()
    budget = Budget(args.max_cost)
    for path in args.configs:
        cfg = RagConfig.model_validate(yaml.safe_load((ROOT / path).read_text()))
        if args.dataset:
            cfg = cfg.model_copy(update={"dataset": args.dataset})
        try:
            run(cfg, budget)
        except BudgetExceeded as e:
            print(f"STOP: {e}")
            break
    print(f"spent this invocation: ${budget.spent:.4f}")


if __name__ == "__main__":
    main()
