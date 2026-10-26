"""Full regression tier (Phase 8.2): rerun the main evaluations, check thresholds, diff per item.

python -m eval.regression [--skip rag agent security] [--max-cost 1.0] [--update-baseline]
python -m eval.regression --ci     fast tier: retrieval on the CI fixture (GitHub Actions)
Needs the full local database and an API key. Unchanged code replays the LLM cache, so a clean
run costs almost nothing; a change that alters prompts or retrieval makes fresh calls.
  -> results/regression/<suite>.csv   per-item pass/fail snapshots of this run
  -> results/regression/summary.md    thresholds table + per-item diffs vs the committed baseline
Exit code 1 if any threshold is breached. `--update-baseline` copies this run's snapshots to
tests/regression/baseline/ (do it only for a run you accept as the new reference).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

import pandas as pd
import yaml

from eval.diff import diff, load, markdown, passed
from eval.run_rag import summarise as rag_summary
from finagent.config import ROOT
from finagent.db import pool

OUT = ROOT / "results/regression"
BASE = ROOT / "tests/regression/baseline"
THRESH = ROOT / "tests/regression/thresholds.yaml"
RETRIEVAL_CFG = "configs/retrieval/C_bge_m3_hybrid_filters_translate_tsrank.yaml"
RAG_CFG = "configs/rag/rag_best_k10.yaml"
CI_CFG = "configs/retrieval/CI_e5_small_hybrid.yaml"
DEV = "eval/datasets/qa_dev.jsonl"
PY = [sys.executable, "-m"]


def sh(*args: str) -> None:
    print("$", " ".join(args), flush=True)
    subprocess.run([*PY, *args], check=True, cwd=ROOT)


def latest(kind: str, name: str, dataset: str = DEV) -> list[tuple[str, dict, dict]]:
    """Read the run this check just made, then delete it: a regression run is a check, not an
    experiment, and must not become the "latest run" that the reports (report_rag) read."""
    with pool().connection() as conn, conn.transaction():
        (run_id,) = conn.execute(
            "SELECT run_id FROM eval_runs WHERE kind = %s AND config->>'name' = %s AND "
            "dataset = %s ORDER BY started_at DESC LIMIT 1",
            (kind, name, dataset),
        ).fetchone()
        rows = conn.execute(
            "SELECT item_id, metrics, output FROM eval_results WHERE run_id = %s", (run_id,)
        ).fetchall()
        conn.execute("DELETE FROM eval_results WHERE run_id = %s", (run_id,))
        conn.execute("DELETE FROM eval_runs WHERE run_id = %s", (run_id,))
    return rows


def snapshot(kind: str, rows) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"id": i, "category": (o or {}).get("type", ""), "success": passed(kind, m)}
            for i, m, o in rows
        ]
    )


def run_ci() -> tuple[dict[str, float], dict[str, pd.DataFrame]]:
    """Fast tier: e5-small retrieval on the CI fixture; no GPU, no API key."""
    sh("eval.run_retrieval", CI_CFG)
    rows = latest("retrieval", "CI_e5_small_hybrid", "eval/datasets/qa_ci.jsonl")
    metrics = {
        "retrieval_ci_subset.recall@5": sum(m["recall@5"] for _, m, _ in rows) / len(rows),
        "retrieval_ci_subset.mrr@10": sum(m["mrr@10"] for _, m, _ in rows) / len(rows),
    }
    return metrics, {"retrieval_ci": snapshot("retrieval", rows)}


def run_suites(skip: set[str], max_cost: float) -> tuple[dict[str, float], dict[str, pd.DataFrame]]:
    metrics: dict[str, float] = {}
    snaps: dict[str, pd.DataFrame] = {}
    sh("eval.run_retrieval", RETRIEVAL_CFG)
    rows = latest("retrieval", "C_bge_m3_hybrid_filters_translate_tsrank")
    metrics["retrieval.recall@5"] = sum(m["recall@5"] for _, m, _ in rows) / len(rows)
    metrics["retrieval.mrr@10"] = sum(m["mrr@10"] for _, m, _ in rows) / len(rows)
    snaps["retrieval"] = snapshot("retrieval", rows)
    if "rag" not in skip:
        sh("eval.run_rag", RAG_CFG, "--max-cost", str(max_cost / 3))
        rows = latest("rag", "rag_best_k10")
        s = rag_summary([m for _, m, _ in rows])
        metrics["rag.numeric_em"] = s["numeric_em"]
        metrics["rag.citation_precision"] = s["citation_precision"]
        metrics["rag.false_abstention_rate"] = s["false_abstention_rate"]
        snaps["rag"] = snapshot("rag", rows)
    if "agent" not in skip:
        sh(
            "eval.run_agent_eval",
            "--modes",
            "routed",
            "--tag",
            "regression",
            "--max-cost",
            str(max_cost / 3),
        )
        items = pd.read_csv(ROOT / "results/agent_items_regression.csv")
        metrics["agent.task_success"] = items["success"].mean()
        metrics["agent.routing_accuracy"] = items["route_ok"].mean()
        snaps["agent"] = items[["id", "kind", "success"]].rename(columns={"kind": "category"})
    if "security" not in skip:
        sh(
            "eval.run_security",
            "--suite",
            "attack",
            "--modes",
            "single",
            "routed",
            "--defences",
            "policy",
            "--tag",
            "security_raw",
            "--out-dir",
            "results/regression",
            "--max-cost",
            str(max_cost / 3),
        )
        items = pd.read_csv(OUT / "security_raw.csv")
        metrics["security.asr_policy_on"] = items["success"].mean()
        snaps["security"] = items[["suite", "mode", "id", "category", "success"]]
    return metrics, snaps


def check(metrics: dict[str, float], t: dict) -> list[tuple[str, float, str, bool]]:
    rows = []
    for key, value in metrics.items():
        suite, name = key.split(".", 1)
        conf = t.get(suite, {})
        if f"{name}_max" in conf:
            lim = conf[f"{name}_max"]
            rows.append((key, value, f"≤ {lim}", value <= lim + 1e-9))
        elif conf.get(name) is not None:
            lim = conf[name]
            rows.append((key, value, f"≥ {lim}", value >= lim - 1e-9))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", nargs="*", default=[], choices=["rag", "agent", "security"])
    ap.add_argument("--max-cost", type=float, default=1.0)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--ci", action="store_true", help="fast tier only (CI fixture)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    metrics, snaps = run_ci() if args.ci else run_suites(set(args.skip), args.max_cost)
    for name, df in snaps.items():
        df.to_csv(OUT / f"{name}.csv", index=False)
    results = check(metrics, yaml.safe_load(THRESH.read_text()))
    lines = ["## Regression check", "", "| Metric | Value | Threshold | |", "|---|---|---|---|"]
    lines += [
        f"| {k} | {v:.3f} | {lim} | {'✅' if ok else '❌ BREACH'} |" for k, v, lim, ok in results
    ]
    for name in snaps:
        base = BASE / f"{name}.csv"
        if base.exists():
            la, a, ta = load(str(base))
            lb, b, tb = load(str(OUT / f"{name}.csv"))
            lines += ["", markdown(f"baseline/{name}", f"this run/{name}", diff(a, b, ta | tb))]
        else:
            lines += ["", f"_no baseline for {name} yet (run with --update-baseline)_"]
    text = "\n".join(lines)
    (OUT / "summary.md").write_text(text + "\n")
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as f:
            f.write(text + "\n")
    if args.update_baseline:
        BASE.mkdir(parents=True, exist_ok=True)
        for name in snaps:
            shutil.copy(OUT / f"{name}.csv", BASE / f"{name}.csv")
        print(f"baseline updated: {', '.join(snaps)}")
    breached = [k for k, _, _, ok in results if not ok]
    if breached:
        print(f"\nREGRESSION: thresholds breached: {', '.join(breached)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
