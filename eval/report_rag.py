"""RAG results table (latest run per config and dataset), with judge columns when available.

python -m eval.report_rag   -> results/rag_dev.csv, results/rag_test.csv
"""

from __future__ import annotations

import pandas as pd

from eval.metrics import bootstrap_ci
from eval.run_rag import summarise
from finagent.config import ROOT, load_config
from finagent.db import pool

DATASETS = {"dev": "eval/datasets/qa_dev.jsonl", "test": "eval/datasets/qa_test.jsonl"}


MIN_UNCACHED = 20  # below this, latency is not reported (cached calls take ~0 ms)


def latest(kind: str, dataset: str) -> tuple[dict[str, list[tuple[str, dict]]], dict[str, dict]]:
    with pool().connection() as conn:
        rows = conn.execute(
            """WITH l AS (SELECT DISTINCT ON (config->>'name') run_id, config->>'name' AS name,
                                 config
                          FROM eval_runs WHERE kind = %s AND dataset = %s
                          ORDER BY config->>'name', started_at DESC)
               SELECT l.name, l.config, r.item_id, r.metrics
               FROM l JOIN eval_results r USING (run_id)""",
            (kind, dataset),
        ).fetchall()
    out: dict[str, list] = {}
    configs: dict[str, dict] = {}
    for name, cfg, item, m in rows:
        out.setdefault(name, []).append((item, m))
        configs[name] = cfg
    return out, configs


def token_cost(ms: list[dict], generator: str) -> float:
    """Cost per query from token counts, so cached re-runs still report what the run costs."""
    spec = load_config().llm.models[generator]
    total = sum(m["tokens_in"] * spec.price_in + m["tokens_out"] * spec.price_out for m in ms)
    return total / 1e6 / len(ms)


def table(dataset: str) -> pd.DataFrame:
    (rag, rag_cfg), (judged, _) = latest("rag", dataset), latest("judge", dataset)
    rows = []
    for name, items in sorted(rag.items()):
        ms = [m for _, m in items]
        s = summarise(ms)
        s["cost_per_query_usd"] = token_cost(ms, rag_cfg[name]["generator"])
        if sum(1 for m in ms if not m["cached"]) < MIN_UNCACHED:
            s["latency_p50_ms"] = s["latency_p95_ms"] = float("nan")
        num = [m["em_any"] for m in ms if m["answerable"] and "em_any" in m]
        _, lo, hi = bootstrap_ci(num)
        row = {"config": name, **{k: round(v, 4) for k, v in s.items()},
               "numeric_em_lo": round(lo, 4), "numeric_em_hi": round(hi, 4)}  # fmt: skip
        n_to_judge = sum(1 for m in ms if not m["abstain"])
        if name in judged and len(judged[name]) == n_to_judge:  # only complete judge runs
            jm = [m for _, m in judged[name]]
            row["faithfulness"] = round(sum(m["faithfulness"] for m in jm) / len(jm), 4)
            row["faithful_share"] = round(sum(m["faithful"] for m in jm) / len(jm), 4)
            corr = [m["correctness"] for m in jm if m["correctness"] is not None]
            row["correctness"] = round(sum(corr) / len(corr), 4) if corr else None
            row["n_judged"] = len(jm)
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    cols = ["config", "n", "numeric_em", "numeric_em_lo", "numeric_em_hi", "citation_precision",
            "citation_recall", "abstain_f1", "false_abstention_rate", "faithfulness", "correctness",
            "latency_p50_ms", "latency_p95_ms", "cost_per_query_usd"]  # fmt: skip
    for split, path in DATASETS.items():
        df = table(path)
        if df.empty:
            continue
        df.to_csv(ROOT / "results" / f"rag_{split}.csv", index=False)
        print(f"\n== {split} ==")
        print(df[[c for c in cols if c in df.columns]].to_string(index=False))


if __name__ == "__main__":
    main()
