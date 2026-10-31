"""SQL fragments shared by the retrieval backends."""

from __future__ import annotations

import os

from finagent.retrieval.types import Filters

# Document types left out of retrieval. Default: the demo app's planted injection page, so it can
# never leak into evaluations. The demo app's MCP server sets this to the evaluation suite's planted
# pages instead (so a live demo cannot retrieve them, but can retrieve its own demo page).
DEFAULT_EXCLUDED = "synthetic_demo"


def excluded_doc_types() -> list[str]:
    raw = os.environ.get("FINAGENT_EXCLUDE_DOC_TYPES", DEFAULT_EXCLUDED)
    return [t.strip() for t in raw.split(",") if t.strip()]


def filter_sql(filters: Filters | None) -> tuple[str, dict]:
    """AND-clauses on documents d: excluded document types, then bank/year metadata filters."""
    clauses = ["AND d.doc_type <> ALL(%(x_types)s)"]
    params: dict = {"x_types": excluded_doc_types()}
    if filters and filters.banks:
        clauses.append("AND d.bank = ANY(%(f_banks)s)")
        params["f_banks"] = filters.banks
    if filters and filters.years:
        clauses.append("AND d.year = ANY(%(f_years)s)")
        params["f_years"] = filters.years
    return " ".join(clauses), params
