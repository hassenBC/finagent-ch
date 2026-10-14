"""Text-to-SQL execution accuracy over the figures (Phase 5.5).

python -m eval.eval_sql [--model deepseek_flash] [--extracted SOURCE] [--max-cost 0.3]
The reference result of each question = its reference SQL run on the GOLD figures. Settings:
  gold       generated SQL on gold figures       -> text-to-SQL errors only
  extracted  generated SQL on extracted figures  -> end-to-end
  oracle     reference SQL on extracted figures  -> extraction errors only
  -> results/figures_sql.csv, results/figures_sql_items.csv
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from pydantic import BaseModel

from finagent.config import ROOT
from finagent.figures.gold_sheet import load_metrics
from finagent.figures.sql_tool import run_figures_query, tool_description
from finagent.llm.client import LLMClient

DATASET = ROOT / "eval/datasets/figures_qa.jsonl"
REL_TOL, ABS_TOL = 0.005, 0.01


class SQLAnswer(BaseModel):
    sql: str


def _cell_eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(a - b) <= max(ABS_TOL, REL_TOL * abs(a))
    return str(a).strip().lower() == str(b).strip().lower()


def _row_covers(ref: dict, pred: dict) -> bool:
    """Every reference value appears in a distinct column of the predicted row."""
    free = list(pred.values())
    for v in ref.values():
        j = next((i for i, w in enumerate(free) if _cell_eq(v, w)), None)
        if j is None:
            return False
        free.pop(j)
    return True


def same_result(ref: list[dict], pred: list[dict], ordered: bool) -> bool:
    if len(ref) != len(pred):
        return False
    if ordered:
        return all(_row_covers(r, p) for r, p in zip(ref, pred, strict=True))
    free = list(pred)
    for r in ref:
        j = next((i for i, p in enumerate(free) if _row_covers(r, p)), None)
        if j is None:
            return False
        free.pop(j)
    return True


def generate_sql(question: str, description: str, llm: LLMClient) -> tuple[str | None, float]:
    messages = [
        {"role": "system", "content": "You write SQL for this tool:\n" + description},
        {"role": "user", "content": f"Question: {question}\nReturn the SQL only."},
    ]
    try:
        r = llm.chat(messages, response_format=SQLAnswer, max_tokens=2000)
    except ValueError:
        return None, 0.0
    return r.parsed.sql, r.cost_usd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="deepseek_flash")
    ap.add_argument("--extracted", default="extracted:deepseek_flash")
    ap.add_argument("--max-cost", type=float, default=0.3)
    args = ap.parse_args()
    items = [json.loads(ln) for ln in DATASET.read_text().splitlines()]
    desc = tool_description(load_metrics())
    llm = LLMClient.from_config(args.model)

    with ThreadPoolExecutor(6) as ex:
        gen = list(ex.map(lambda it: generate_sql(it["question"], desc, llm), items))
    spent = sum(c for _, c in gen)
    if spent > args.max_cost:
        raise SystemExit(f"cost ${spent:.3f} above cap")

    rows = []
    for it, (sql, _) in zip(items, gen, strict=True):
        ref = run_figures_query(it["reference_sql"], source="gold")
        if not ref.ok:
            raise SystemExit(f"{it['id']}: reference SQL failed: {ref.error}")
        runs = {
            "gold": run_figures_query(sql, source="gold") if sql else None,
            "extracted": run_figures_query(sql, source=args.extracted) if sql else None,
            "oracle": run_figures_query(it["reference_sql"], source=args.extracted),
        }
        for setting, r in runs.items():
            rows.append({
                "id": it["id"], "setting": setting, "sql_ok": bool(r and r.ok),
                "correct": bool(r and r.ok and same_result(ref.rows, r.rows, it["ordered"])),
                "error": (r.error if r else "no SQL generated"),
                "sql": sql if setting != "oracle" else it["reference_sql"],
                "n_ref_rows": len(ref.rows),
            })  # fmt: skip
    df = pd.DataFrame(rows)
    summary = (
        df.groupby("setting")
        .agg(n=("id", "size"), execution_accuracy=("correct", "mean"), sql_valid=("sql_ok", "mean"))
        .round(3)
        .reset_index()
    )
    summary["generator"] = args.model
    summary["cost_usd"] = round(spent, 4)
    summary.to_csv(ROOT / "results/figures_sql.csv", index=False)
    df.to_csv(ROOT / "results/figures_sql_items.csv", index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
