"""Aggregate the latest retrieval run per config into results/*.csv and a recall@5 chart."""

from __future__ import annotations

import pandas as pd

from eval.metrics import bootstrap_ci, percentile
from finagent.config import ROOT
from finagent.db import pool

RESULTS = ROOT / "results"
METRICS = ["recall@1", "recall@3", "recall@5", "recall@10", "mrr@10", "ndcg@10"]


def latest_runs(dataset: str = "eval/datasets/qa_dev.jsonl") -> pd.DataFrame:
    """One row per (config name, question) from the newest run of each config."""
    with pool().connection() as conn:
        rows = conn.execute(
            """WITH latest AS (
                   SELECT DISTINCT ON (config->>'name') run_id, config->>'name' AS name
                   FROM eval_runs WHERE kind = 'retrieval' AND dataset = %s
                   ORDER BY config->>'name', started_at DESC)
               SELECT l.name, r.item_id, r.metrics, r.output->>'type', r.output->>'lang'
               FROM latest l JOIN eval_results r USING (run_id)""",
            (dataset,),
        ).fetchall()
    return pd.DataFrame(
        [{"config": n, "item": i, "type": t, "lang": lg, **m} for n, i, m, t, lg in rows]
    )


def summarise(df: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    out = []
    for key, g in df.groupby(["config", *(by or [])]):
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(["config", *(by or [])], key, strict=True))
        row["n"] = len(g)
        for m in METRICS:
            mean, lo, hi = bootstrap_ci(g[m].tolist())
            row[m] = round(mean, 4)
            if m in ("recall@5", "mrr@10"):
                row[f"{m}_lo"], row[f"{m}_hi"] = round(lo, 4), round(hi, 4)
        row["latency_p50_ms"] = round(percentile(g["latency_ms"].tolist(), 50), 1)
        row["latency_p95_ms"] = round(percentile(g["latency_ms"].tolist(), 95), 1)
        out.append(row)
    return pd.DataFrame(out)


def chart(summary: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = summary.sort_values("recall@5")
    fig, ax = plt.subplots(figsize=(8, 0.35 * len(s) + 1.5))
    err = [s["recall@5"] - s["recall@5_lo"], s["recall@5_hi"] - s["recall@5"]]
    ax.barh(s["config"], s["recall@5"], xerr=err, color="#4c78a8", ecolor="#333", capsize=2)
    ax.set_xlabel("recall@5 on qa_dev (95 % bootstrap CI)")
    ax.set_xlim(0, 1)
    fig.tight_layout()
    fig.savefig(RESULTS / "retrieval.png", dpi=150)


def main() -> None:
    import sys

    RESULTS.mkdir(exist_ok=True)
    if "--test" in sys.argv:  # final configs on the held-out test set
        df = latest_runs("eval/datasets/qa_test.jsonl")
        summarise(df).to_csv(RESULTS / "retrieval_test.csv", index=False)
        summarise(df, by=["type"]).to_csv(RESULTS / "retrieval_test_by_type.csv", index=False)
        print(
            summarise(df)[
                [
                    "config",
                    "n",
                    "recall@5",
                    "recall@5_lo",
                    "recall@5_hi",
                    "mrr@10",
                    "latency_p50_ms",
                ]
            ].to_string(index=False)
        )
        return
    df = latest_runs()
    if df.empty:
        print("no retrieval runs yet")
        return
    summary = summarise(df)
    summary.to_csv(RESULTS / "retrieval.csv", index=False)
    summarise(df, by=["type"]).to_csv(RESULTS / "retrieval_by_type.csv", index=False)
    summarise(df, by=["lang"]).to_csv(RESULTS / "retrieval_by_lang.csv", index=False)
    chart(summary)
    print(
        summary[
            [
                "config",
                "n",
                "recall@5",
                "recall@5_lo",
                "recall@5_hi",
                "mrr@10",
                "ndcg@10",
                "latency_p50_ms",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
