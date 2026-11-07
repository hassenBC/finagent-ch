from finagent.retrieval.sql import filter_sql
from finagent.retrieval.types import Filters


def test_demo_documents_are_excluded_by_default(monkeypatch):
    monkeypatch.delenv("FINAGENT_EXCLUDE_DOC_TYPES", raising=False)
    where, params = filter_sql(None)
    assert "d.doc_type <> ALL(%(x_types)s)" in where and params["x_types"] == ["synthetic_demo"]


def test_exclusions_come_from_the_environment_and_combine_with_filters(monkeypatch):
    monkeypatch.setenv("FINAGENT_EXCLUDE_DOC_TYPES", "synthetic_injection")
    where, params = filter_sql(Filters(banks=["efg"], years=[2025]))
    assert params == {"x_types": ["synthetic_injection"], "f_banks": ["efg"], "f_years": [2025]}
    assert where.count("AND ") == 3


def test_empty_exclusion_list_excludes_nothing(monkeypatch):
    monkeypatch.setenv("FINAGENT_EXCLUDE_DOC_TYPES", "")
    _, params = filter_sql(None)
    assert params["x_types"] == []
