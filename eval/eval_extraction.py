"""Extracted figures vs hand-labelled gold (Phase 5.3).

python -m eval.eval_extraction [--source extracted:deepseek_flash]
  -> results/extraction.csv         per metric + overall: accuracy, coverage, precision
  -> results/extraction_errors.csv  every non-correct cell with its error type
Accuracy = correct / gold cells with a value (tolerance 0.5 % relative); coverage = extracted /
gold cells with a value; precision = correct / extracted.
"""

from __future__ import annotations

import argparse
from collections import Counter

import pandas as pd

from finagent.config import ROOT
from finagent.db import pool

TOL = 0.005


def matches(gold: float, x: float) -> bool:
    return abs(x - gold) <= TOL * abs(gold) if gold else abs(x) < 1e-9


def classify(
    gold: float | None, ext: float | None, prior: float | None, others: dict[str, float]
) -> str:
    """Outcome of one (bank, year, metric) cell. `prior` = gold of the same metric one year
    earlier; `others` = gold values of the other metrics of the same bank and year."""
    if gold is None:
        return "both_empty" if ext is None else "spurious"
    if ext is None:
        return "missing"
    if matches(gold, ext):
        return "correct"
    if matches(gold, -ext):
        return "sign"
    if any(matches(gold, ext * f) for f in (1e3, 1e-3, 1e6, 1e-6)):
        return "unit_scale"
    if prior is not None and matches(prior, ext):
        return "prior_year"
    if any(matches(v, ext) for v in others.values()):
        return "wrong_metric"
    return "wrong_value"


def load(source: str) -> dict[tuple[str, int, str], float]:
    with pool().connection() as conn:
        rows = conn.execute(
            "SELECT bank, year, metric, value FROM figures WHERE source = %s", (source,)
        ).fetchall()
    return {(b, y, m): float(v) for b, y, m, v in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="extracted:deepseek_flash")
    args = ap.parse_args()
    gold_csv = pd.read_csv(ROOT / "data/gold/figures_gold.csv")
    gold, ext = load("gold"), load(args.source)
    if not gold:
        raise SystemExit("no gold figures loaded: python -m finagent.figures.load_gold")
    cells = [(r.bank, int(r.year), r.metric) for r in gold_csv.itertuples()]
    rows = []
    for b, y, m in cells:
        others = {k[2]: v for k, v in gold.items() if k[:2] == (b, y) and k[2] != m}
        g, x = gold.get((b, y, m)), ext.get((b, y, m))
        rows.append({"bank": b, "year": y, "metric": m, "gold": g, "extracted": x,
                     "outcome": classify(g, x, gold.get((b, y - 1, m)), others)})  # fmt: skip
    df = pd.DataFrame(rows)

    def summary(d: pd.DataFrame) -> dict:
        n_gold = int(d["gold"].notna().sum())
        n_ext = int(d["extracted"].notna().sum())
        n_ok = int((d["outcome"] == "correct").sum())
        return {"n_cells": len(d), "n_gold": n_gold, "n_extracted": n_ext, "correct": n_ok,
                "accuracy": round(n_ok / n_gold, 3) if n_gold else None,
                "coverage": round(n_ext / n_gold, 3) if n_gold else None,
                "precision": round(n_ok / n_ext, 3) if n_ext else None,
                **Counter(d["outcome"])}  # fmt: skip

    table = pd.DataFrame(
        [{"metric": m, **summary(d)} for m, d in df.groupby("metric")]
        + [{"metric": "ALL", **summary(df)}]
    ).fillna(0)
    out = ROOT / "results"
    table.to_csv(out / "extraction.csv", index=False)
    df[~df["outcome"].isin(["correct", "both_empty"])].to_csv(
        out / "extraction_errors.csv", index=False
    )
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
