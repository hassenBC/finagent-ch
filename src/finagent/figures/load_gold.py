"""Load hand-labelled gold figures into `figures` with source 'gold' (Phase 5.2).

python -m finagent.figures.load_gold  (replaces all gold rows; cells without a value are skipped)
"""

from __future__ import annotations

import csv

from finagent.db import pool
from finagent.figures.gold_sheet import GOLD, load_metrics


def parse_value(text: str) -> float | None:
    """Plain number with a dot decimal; Swiss apostrophes and spaces allowed as separators.
    Commas are refused: "15,2" (French decimal) and "1,234" (thousands) are ambiguous."""
    t = (text or "").strip().replace("'", "").replace("’", "").replace(" ", "")
    if "," in t:
        raise ValueError(f"use a dot decimal and no commas: {text!r}")
    return float(t) if t else None


def load_rows() -> list[dict]:
    metrics = load_metrics()
    rows = []
    with GOLD.open() as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            if r["metric"] not in metrics:
                raise ValueError(f"line {i}: unknown metric {r['metric']!r}")
            if r["unit"] != metrics[r["metric"]]["unit"]:
                raise ValueError(f"line {i}: unit {r['unit']!r} != {metrics[r['metric']]['unit']}")
            value = parse_value(r["value"])
            if value is None:
                continue
            if not r["page"].strip():
                raise ValueError(f"line {i}: value without a page")
            rows.append(r | {"value": value, "year": int(r["year"]), "page": int(r["page"])})
    return rows


def main() -> None:
    rows = load_rows()
    with pool().connection() as conn, conn.transaction():
        docs = {
            (b, y): d
            for d, b, y in conn.execute(
                "SELECT doc_id, bank, year FROM documents WHERE doc_type = 'annual_report'"
            )
        }
        conn.execute("DELETE FROM figures WHERE source = 'gold'")
        for r in rows:
            conn.execute(
                "INSERT INTO figures (bank, year, metric, value, unit, doc_id, page_no, source)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, 'gold')",
                (r["bank"], r["year"], r["metric"], r["value"], r["unit"],
                 docs[(r["bank"], r["year"])], r["page"]),
            )  # fmt: skip
    print(f"loaded {len(rows)} gold figures")


if __name__ == "__main__":
    main()
