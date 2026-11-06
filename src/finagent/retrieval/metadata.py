"""Extract bank / fiscal-year filters from a question."""

from __future__ import annotations

import re

from finagent.retrieval.types import Filters

BANK_ALIASES = {
    "juliusbaer": ["julius baer", "julius bär", "julius bar", "bank julius"],
    "vontobel": ["vontobel"],
    "efg": ["efg"],
    "swissquote": ["swissquote"],
    "bcv": ["bcv", "banque cantonale vaudoise", "vaudoise"],
    "bcge": ["bcge", "banque cantonale de genève", "banque cantonale de geneve", "genevoise"],
}
CORPUS_YEARS = (2024, 2025)
_YEAR = re.compile(r"\b(20\d\d)\b")


def extract_filters(query: str) -> Filters | None:
    """Banks named in the question and the fiscal years it refers to.

    A year before the corpus (e.g. 'as at 31 December 2023') is a prior-year column of the 2024
    report, so it maps to 2024. A question naming 2024 only is kept to 2024 (the 2025 report also
    holds 2024 columns, but the question asks about the 2024 report).
    """
    q = query.lower()
    banks = [
        b
        for b, names in BANK_ALIASES.items()
        if any(re.search(rf"\b{re.escape(n)}\b", q) for n in names)
    ]
    found = {int(y) for y in _YEAR.findall(query)}
    years = {y for y in found if y in CORPUS_YEARS}
    if any(y < CORPUS_YEARS[0] for y in found):
        years.add(CORPUS_YEARS[0])
    if not banks and not years:
        return None
    return Filters(banks=banks or None, years=sorted(years) or None)
