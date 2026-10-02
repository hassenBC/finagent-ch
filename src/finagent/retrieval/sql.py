"""SQL fragments shared by the retrieval backends."""

from __future__ import annotations

from finagent.retrieval.types import Filters


def filter_sql(filters: Filters | None) -> tuple[str, dict]:
    """AND-clauses on documents d for bank/year metadata filters."""
    if not filters:
        return "", {}
    clauses, params = [], {}
    if filters.banks:
        clauses.append("AND d.bank = ANY(%(f_banks)s)")
        params["f_banks"] = filters.banks
    if filters.years:
        clauses.append("AND d.year = ANY(%(f_years)s)")
        params["f_years"] = filters.years
    return " ".join(clauses), params
