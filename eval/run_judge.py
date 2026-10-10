"""Judge the latest RAG run of each named config and store the verdicts as a 'judge' run.

python -m eval.run_judge rag_best_k5 [...] [--dataset ...] [--max-cost 0.5] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

from psycopg.types.json import Jsonb

from eval.judge import judge, scores
from eval.run_rag import Budget, BudgetExceeded
from eval.run_retrieval import git_sha
from finagent.config import ROOT, load_config
from finagent.db import pool
from finagent.llm.client import LLMClient


def latest_rag_run(name: str, dataset: str) -> tuple[str, list[tuple[str, dict, dict]]]:
    with pool().connection() as conn:
        run_id = conn.execute(
            """SELECT run_id FROM eval_runs WHERE kind = 'rag' AND config->>'name' = %s
               AND dataset = %s ORDER BY started_at DESC LIMIT 1""",
            (name, dataset),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT item_id, metrics, output FROM eval_results WHERE run_id = %s ORDER BY item_id",
            (run_id,),
        ).fetchall()
    return str(run_id), rows


def chunk_text(ids: list[int]) -> dict[int, str]:
    with pool().connection() as conn:
        return dict(
            conn.execute(
                "SELECT chunk_id, content FROM chunks WHERE chunk_id = ANY(%s)", (ids,)
            ).fetchall()
        )


def run(name: str, dataset: str, budget: Budget, limit: int | None, model: str) -> None:
    items = {
        r["id"]: r for r in (json.loads(ln) for ln in (ROOT / dataset).read_text().splitlines())
    }
    rag_run, rows = latest_rag_run(name, dataset)
    rows = [r for r in rows if not r[1]["abstain"]][:limit]  # abstentions have no claims to judge
    llm = LLMClient.from_config(model)
    texts = chunk_text([c["chunk_id"] for _, _, o in rows for c in o["citations"]])

    def one(row):
        item_id, m, o = row
        it = items[item_id]
        cited = [texts[c["chunk_id"]] for c in o["citations"]]
        if not cited:  # claims without any valid citation cannot be faithful
            return item_id, {"n_claims": None, "faithfulness": 0.0, "faithfulness_lenient": 0.0,
                             "faithful": 0.0, "correctness": None, "judged": 0.0}, None  # fmt: skip
        budget.check()
        j, cost = judge(it["question"], o["answer"], cited, it["answer"], llm)
        budget.charge(cost)
        return item_id, {**scores(j), "judged": 1.0, "cost_usd": cost}, j.model_dump()

    out = []
    with ThreadPoolExecutor(6) as ex:
        for fut in [ex.submit(one, r) for r in rows]:
            try:
                out.append(fut.result())
            except BudgetExceeded as e:
                print(f"STOP: {e}", flush=True)
                return
    run_id = uuid.uuid4()
    with pool().connection() as conn, conn.transaction():
        conn.execute(
            "INSERT INTO eval_runs (run_id, kind, config, git_sha, dataset) "
            "VALUES (%s, 'judge', %s, %s, %s)",
            (
                run_id,
                Jsonb({"name": name, "rag_run_id": rag_run, "judge": model}),
                git_sha(),
                dataset,
            ),  # fmt: skip
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO eval_results (run_id, item_id, metrics, output) "
                "VALUES (%s, %s, %s, %s)",
                [(run_id, i, Jsonb(m), Jsonb(j or {})) for i, m, j in out],
            )
    judged = [m for _, m, _ in out]
    f = sum(m["faithfulness"] for m in judged) / len(judged)
    faithful = sum(m["faithful"] for m in judged) / len(judged)
    corr = [m["correctness"] for m in judged if m["correctness"] is not None]
    print(
        f"{name:22} judged={len(judged)} faithfulness={f:.3f} faithful={faithful:.3f} "
        f"correctness={sum(corr) / max(1, len(corr)):.3f} spent=${budget.spent:.4f}",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--dataset", default="eval/datasets/qa_dev.jsonl")
    ap.add_argument("--max-cost", type=float, default=0.5)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default=load_config().llm.judge)
    args = ap.parse_args()
    budget = Budget(args.max_cost)
    for n in args.names:
        run(n, args.dataset, budget, args.limit, args.model)
    print(f"spent this invocation: ${budget.spent:.4f}")


if __name__ == "__main__":
    main()
