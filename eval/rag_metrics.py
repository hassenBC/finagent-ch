"""Automatic answer metrics (no judge): numeric match, citations, abstention."""

from __future__ import annotations

import re

from eval.dataset_utils import evidence_on_pages
from finagent.ingest.text import normalise_numbers

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre"
)
_DATES = [
    re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b"),  # 31.12.2024
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th|er)?\s+(?:{_MONTHS})\b", re.I),  # 31 December
    re.compile(r"\b(?:19|20)\d\d\b"),  # years
    re.compile(r"\[S\d+\]"),  # citation markers
]
_NUM = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(%|percent|pour\s?cent|bn|billions?|milliards?|mrd|mn|m\b|millions?|mio|"
    r"thousands?|milliers?|k\b)?",
    re.I,
)
_SCALE = {  # multiplier into CHF millions
    "bn": 1e3, "billion": 1e3, "billions": 1e3, "milliard": 1e3, "milliards": 1e3, "mrd": 1e3,
    "m": 1.0, "mn": 1.0, "million": 1.0, "millions": 1.0, "mio": 1.0,
    "thousand": 1e-3, "thousands": 1e-3, "millier": 1e-3, "milliers": 1e-3, "k": 1e-3,
}  # fmt: skip


def numbers_in(text: str) -> list[tuple[float, str]]:
    """(value, unit word) for every number in an answer, dates/years/citations removed."""
    t = normalise_numbers(text)
    for pat in _DATES:
        t = pat.sub(" ", t)
    return [(float(v), (u or "").lower().replace(" ", "")) for v, u in _NUM.findall(t)]


def to_unit(value: float, word: str, unit: str) -> float:
    """Convert a parsed number to the gold unit using the scale word that follows it."""
    if unit in ("pct", "count", "ratio", "none"):
        return value
    scale = _SCALE.get(word)
    if scale is None:  # bare number: raw francs if huge, else assume it is already in the gold unit
        scale = 1e-6 if (abs(value) >= 1e5 and unit != "CHF") else 1.0
        if unit == "CHF":
            return value
    in_m = value * scale
    return {"CHF_m": in_m, "CHF_bn": in_m / 1e3, "CHF": in_m * 1e6}[unit]


def numeric_match(answer: str, gold: dict) -> dict:
    """em_first: the first number matches; em_any: some number matches (comparison answers
    usually state the inputs before the result)."""
    want, tol, unit = gold["value"], gold["tolerance"], gold["unit"]
    nums = numbers_in(answer)
    if unit == "pct":
        pct = [(v, w) for v, w in nums if w in ("%", "percent", "pourcent")]
        nums = pct or nums
    hits = [abs(abs(to_unit(v, w, unit)) - abs(want)) <= tol for v, w in nums]
    return {"em_first": float(bool(hits) and hits[0]), "em_any": float(any(hits))}


def citation_scores(
    cited_pages: list[tuple[int, int, int]], relevant: set, page_text: dict, evidence: str
) -> list[bool]:
    """Per citation (doc, page_start, page_end): correct if it overlaps a gold/alternate page or
    one of its pages contains the evidence."""
    out = []
    for doc, a, b in cited_pages:
        pages = [(doc, p) for p in range(a, b + 1)]
        ok = any(p in relevant for p in pages) or (
            bool(evidence) and evidence_on_pages(evidence, [page_text.get(p, "") for p in pages])
        )
        out.append(ok)
    return out


def abstention_scores(rows: list[dict]) -> dict:
    """rows: {answerable, abstain}. Precision/recall/F1 of abstaining on unanswerable items."""
    tp = sum(1 for r in rows if r["abstain"] and not r["answerable"])
    fp = sum(1 for r in rows if r["abstain"] and r["answerable"])
    fn = sum(1 for r in rows if not r["abstain"] and not r["answerable"])
    n_ans = sum(1 for r in rows if r["answerable"])
    p = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * rec / (p + rec) if p + rec else 0.0
    return {"abstain_precision": p, "abstain_recall": rec, "abstain_f1": f1,
            "false_abstention_rate": fp / n_ans if n_ans else 0.0}  # fmt: skip
