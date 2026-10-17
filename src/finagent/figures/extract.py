"""LLM extraction of key figures, one call per (bank, year, metric), validated in code (Phase 5.3).

python -m finagent.figures.extract [--model deepseek_flash] [--max-cost 0.5] [--limit N]
  -> figures rows with source 'extracted:<model>' (replaced on each run)
  -> eval/extraction/log.csv (git-ignored): every cell with its outcome / rejection reason
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Literal

from pydantic import BaseModel

from finagent.config import ROOT
from finagent.db import pool
from finagent.figures.gold_sheet import load_metrics
from finagent.ingest.text import BANK_NAMES, normalise_numbers
from finagent.llm.client import LLMClient
from finagent.retrieval.pipeline import retrieve
from finagent.retrieval.types import Filters, Hit, RetrievalConfig

RETRIEVAL = "configs/retrieval/C_bge_m3_hybrid_filters_translate_tsrank.yaml"
LOG = ROOT / "eval/extraction/log.csv"
TOP_K = 8
IN_MILLIONS = {"CHF": 1e-6, "CHF_k": 1e-3, "CHF_m": 1.0, "CHF_bn": 1e3}
POSITIVE = {"operating_expenses", "headcount_fte", "total_assets", "assets_under_management"}
ReportedUnit = Literal["CHF", "CHF_k", "CHF_m", "CHF_bn", "pct", "count"]


class RawFigure(BaseModel):
    """What the LLM returns."""

    found: bool
    value: float | None = None  # exactly as printed in the source
    reported_unit: ReportedUnit | None = None  # scale of `value` as printed
    period_end: date | None = None  # end of the period of the column the value was read from
    source: str | None = None  # e.g. "S3"
    quote: str | None = None  # the row or sentence containing the value, copied from the source


class ExtractedFigure(BaseModel):
    metric: str
    value: float  # in the metric's unit
    unit: Literal["CHF_m", "CHF_bn", "pct", "count"]
    period_end: date
    page: int
    quote: str
    doc_id: int
    chunk_id: int


def to_metric_unit(value: float, reported: str, unit: str) -> float:
    if unit in ("pct", "count"):
        return value
    in_m = value * IN_MILLIONS[reported]
    return in_m if unit == "CHF_m" else in_m / 1e3


def _norm(text: str) -> str:
    text = normalise_numbers(text.replace("|", " ")).lower()
    return re.sub(r"\s+", " ", text).strip()


def _numbers(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", normalise_numbers(text))]


def _unit_fits(reported: str, unit: str) -> bool:
    return reported == unit if unit in ("pct", "count") else reported in IN_MILLIONS


def check(
    r: RawFigure, metric: str, unit: str, year: int, sources: dict[str, Hit]
) -> tuple[ExtractedFigure | None, str]:
    """Validate an LLM answer; return (figure, 'ok') or (None, reason)."""
    if not r.found:
        return None, "not_found"
    if r.value is None or r.reported_unit is None or not r.period_end or not r.quote:
        return None, "incomplete"
    hit = sources.get((r.source or "").strip().strip("[]"))
    if hit is None:
        return None, "bad_source"
    if r.period_end.year != year:
        return None, "prior_year_period" if r.period_end.year == year - 1 else "wrong_period"
    if _norm(r.quote) not in _norm(hit.content):
        return None, "quote_not_in_source"
    if not any(abs(n - abs(r.value)) <= 1e-6 * max(1.0, abs(r.value)) for n in _numbers(r.quote)):
        return None, "value_not_in_quote"
    if not _unit_fits(r.reported_unit, unit):
        return None, "unit_mismatch"
    value = to_metric_unit(r.value, r.reported_unit, unit)
    if metric in POSITIVE:  # Swiss GAAP prints expenses as negative numbers
        value = abs(value)
    return ExtractedFigure(
        metric=metric, value=value, unit=unit,
        period_end=r.period_end, page=hit.page_start, quote=r.quote, doc_id=hit.doc_id,
        chunk_id=hit.chunk_id,
    ), "ok"  # fmt: skip


PROMPT = """Extract one key figure from the annual report of {bank}, fiscal year {year}.

Metric: {metric} — {definition}
{caveat}
Rules:
- The group / consolidated figure for fiscal year {year} (period ending 31 December {year}).
  Tables usually show the prior year next to it: never take the prior-year column.
- Prefer the reported (IFRS or Swiss GAAP) figure over an "adjusted" or "underlying" one,
  unless only an adjusted figure exists.
- value: the number exactly as printed (same digits, no rescaling); reported_unit: its scale
  (CHF, CHF_k, CHF_m, CHF_bn, pct or count) from the table header or the sentence.
- quote: copy the table row or sentence that contains the value, verbatim from the source.
- source: the id of the source you read it from, e.g. S3.
- If the sources do not contain this metric for {year}, return found = false.

Sources:
{sources}"""


def _render(sources: dict[str, Hit]) -> str:
    return "\n\n".join(f"[{sid}] (page {h.page_start})\n{h.content}" for sid, h in sources.items())


def retrieve_cell(bank: str, year: int, m: dict, cfg: RetrievalConfig) -> list[Hit]:
    """Candidate chunks for one cell: all synonyms (EN + FR) as one query, bank/year filtered."""
    return retrieve(" ".join(m["synonyms"]) + f" {year}", cfg, Filters(banks=[bank], years=[year]))


def ask(bank, year, metric, m, hits, llm) -> tuple[RawFigure | None, float]:
    sources = {f"S{i}": h for i, h in enumerate(hits, 1)}
    content = PROMPT.format(
        bank=BANK_NAMES.get(bank, bank), year=year, metric=metric, definition=m["definition"],
        caveat=f"Note: {' '.join(m['caveat'].split())}\n" if m.get("caveat") else "",
        sources=_render(sources),
    )  # fmt: skip
    messages = [{"role": "user", "content": content}]
    try:
        r = llm.chat(messages, response_format=RawFigure, max_tokens=2000)
    except ValueError:  # truncated or empty JSON: retry once with a larger budget
        try:
            r = llm.chat(messages, response_format=RawFigure, max_tokens=4000)
        except ValueError:
            return None, 0.0
    return r.parsed, r.cost_usd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="deepseek_flash")
    ap.add_argument("--max-cost", type=float, default=0.5)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    metrics = load_metrics()
    cfg = RetrievalConfig.from_yaml(RETRIEVAL).model_copy(
        update={"top_k": TOP_K, "translate_cross_lingual": False}  # synonyms cover EN and FR
    )
    with pool().connection() as conn:
        docs = conn.execute(
            "SELECT bank, year FROM documents WHERE doc_type = 'annual_report' ORDER BY bank, year"
        ).fetchall()
    cells = [(b, y, k) for b, y in docs for k in metrics][: args.limit]
    # retrieval runs the embedding model on the GPU: do it sequentially, then the LLM in parallel
    hits = {c: retrieve_cell(c[0], c[1], metrics[c[2]], cfg) for c in cells}
    llm = LLMClient.from_config(args.model)
    spent = 0.0
    results = []

    def run(c):
        b, y, k = c
        return c, *ask(b, y, k, metrics[k], hits[c], llm)

    with ThreadPoolExecutor(6) as ex:
        for c, raw, cost in ex.map(run, cells):
            spent += cost
            b, y, k = c
            sources = {f"S{i}": h for i, h in enumerate(hits[c], 1)}
            fig, reason = (None, "llm_error") if raw is None else check(
                raw, k, metrics[k]["unit"], y, sources)  # fmt: skip
            results.append((c, raw, fig, reason))
            if spent > args.max_cost:
                print(f"STOP: cost cap ${args.max_cost} reached")
                break

    source = f"extracted:{args.model}"
    with pool().connection() as conn, conn.transaction():
        conn.execute("DELETE FROM figures WHERE source = %s", (source,))
        for (b, y, _), _, fig, _ in results:
            if fig:
                conn.execute(
                    "INSERT INTO figures (bank, year, metric, value, unit, doc_id, page_no,"
                    " source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (b, y, fig.metric, fig.value, fig.unit, fig.doc_id, fig.page, source),
                )
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bank", "year", "metric", "reason", "value", "unit", "page", "raw_value",
                    "raw_unit", "raw_period_end", "quote"])  # fmt: skip
        for (b, y, k), raw, fig, reason in results:
            w.writerow([b, y, k, reason, fig.value if fig else "", fig.unit if fig else "",
                        fig.page if fig else "", raw.value if raw else "",
                        raw.reported_unit if raw else "", raw.period_end if raw else "",
                        (raw.quote or "")[:200] if raw else ""])  # fmt: skip
    print(f"{len(results)} cells, stored {sum(1 for r in results if r[2])}, spent ${spent:.4f}")
    print(dict(Counter(r[3] for r in results)))


if __name__ == "__main__":
    main()
