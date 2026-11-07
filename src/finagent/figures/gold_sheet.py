"""Helper for hand-labelling gold figures (Phase 5.2).

Keyword search only — no LLM — so the gold stays independent of the extractor.

python -m finagent.figures.gold_sheet
  -> data/gold/figures_gold.csv   template, one row per bank x year x metric (never overwritten)
  -> eval/figures_sheet/sheet.md  git-ignored: candidate pages and matching lines per cell
"""

from __future__ import annotations

import csv
import re

import yaml

from finagent.config import ROOT
from finagent.db import pool

METRICS = ROOT / "data/gold/metrics.yaml"
GOLD = ROOT / "data/gold/figures_gold.csv"
SHEET = ROOT / "eval/figures_sheet/sheet.md"
FIELDS = ["bank", "year", "metric", "value", "unit", "page", "note"]
KEY_PAGE = re.compile(
    r"key figures|chiffres[- ]clés|at a glance|en bref|five-year|financial highlights", re.I
)
NUMBER = re.compile(r"\d[\d'’ ,.]*\d|\d")
RULES = """# Gold figures — candidate pages (keyword search, not verified)

Fill `data/gold/figures_gold.csv`. Rules:
- the group / consolidated figure at 31 Dec of the fiscal year, from the **current-year** column;
- the unit given in `metrics.yaml` (convert if the report uses another scale);
- `page` = PDF page index (what your viewer shows);
- leave `value` empty if the report does not give the metric;
- put anything non-obvious in `note` (e.g. "only average FTE", "AuM = avoirs administrés").
"""


def load_metrics() -> dict[str, dict]:
    return yaml.safe_load(METRICS.read_text())["metrics"]


def candidates(
    text_by_page: dict[int, str], synonyms: list[str], top: int = 4
) -> list[tuple[int, list[str]]]:
    """Pages whose lines mention a synonym next to a number; key-figure pages first."""
    rx = re.compile(r"\b(?:" + "|".join(re.escape(s) for s in synonyms) + r")\b", re.I)
    scored = []
    for page, text in text_by_page.items():
        text = text or ""
        lines = [
            ln.strip()
            for ln in text.splitlines()
            if rx.search(ln) and NUMBER.search(ln) and not ln.startswith("Bank: ")
        ]
        if lines:
            lines.sort(key=lambda ln: "|" not in ln)  # table rows first
            score = sum(3 if "|" in ln else 1 for ln in lines) + (5 if KEY_PAGE.search(text) else 0)
            scored.append((score, page, lines))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(page, lines[:3]) for _, page, lines in scored[:top]]


def main() -> None:
    metrics = load_metrics()
    with pool().connection() as conn:
        docs = conn.execute(
            "SELECT doc_id, bank, year FROM documents "
            "WHERE doc_type = 'annual_report' ORDER BY bank, year"
        ).fetchall()
        # table-aware chunks keep tables as pipe rows (page text flattens them)
        sql = ("SELECT page_start, string_agg(content, E'\\n' ORDER BY chunk_id) FROM chunks "
               "WHERE doc_id = %s AND chunker = 'table_aware' GROUP BY page_start")  # fmt: skip
        pages = {d: dict(conn.execute(sql, (d,)).fetchall()) for d, _, _ in docs}
    out, rows = [RULES], []
    for doc_id, bank, year in docs:
        out.append(f"\n## {bank} {year} (doc {doc_id})\n")
        for name, m in metrics.items():
            rows.append(dict.fromkeys(FIELDS, "") | {"bank": bank, "year": year,
                        "metric": name, "unit": m["unit"]})  # fmt: skip
            out.append(f"**{name}** ({m['unit']})")
            for page, lines in candidates(pages[doc_id], m["synonyms"]):
                out.append(f"- p. {page}: " + " ⏐ ".join(ln[:160] for ln in lines))
            out.append("")
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    SHEET.write_text("\n".join(out))
    if not GOLD.exists():
        with GOLD.open("w", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            w.writerows(rows)
    print(f"wrote {SHEET} and {GOLD} ({len(rows)} cells)")


if __name__ == "__main__":
    main()
