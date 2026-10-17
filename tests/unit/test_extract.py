from datetime import date

from finagent.figures.extract import RawFigure, check, to_metric_unit
from finagent.retrieval.types import Hit


def hit(cid, page, content):
    return Hit(chunk_id=cid, doc_id=2, page_start=page, page_end=page, content=content,
               score=1.0, source="fused")  # fmt: skip


SOURCES = {
    "S1": hit(10, 5, "| IFRS net profit   | 763.8   | 1,022.3 |\n| Total assets | 107,488.9 |"),
    "S2": hit(11, 69, "| Effectif | 1'010 | 1'021 |"),
}


def raw(**kw):
    base = dict(found=True, value=763.8, reported_unit="CHF_m", period_end=date(2025, 12, 31),
                source="S1", quote="IFRS net profit | 763.8 | 1,022.3")  # fmt: skip
    return RawFigure(**(base | kw))


def test_valid_figure_is_accepted_with_page_from_the_chunk():
    fig, reason = check(raw(), "net_profit", "CHF_m", 2025, SOURCES)
    assert reason == "ok" and fig.value == 763.8 and fig.page == 5 and fig.chunk_id == 10


def test_quote_whitespace_and_pipes_do_not_matter():
    fig, reason = check(raw(quote="IFRS  net profit 763.8"), "net_profit", "CHF_m", 2025, SOURCES)
    assert reason == "ok"


def test_prior_year_period_is_rejected():
    _, reason = check(raw(period_end=date(2024, 12, 31)), "net_profit", "CHF_m", 2025, SOURCES)
    assert reason == "prior_year_period"


def test_quote_not_in_chunk_is_rejected():
    _, reason = check(raw(quote="Net profit 800.0"), "net_profit", "CHF_m", 2025, SOURCES)
    assert reason == "quote_not_in_source"


def test_value_not_in_quote_is_rejected():
    _, reason = check(raw(value=1022.4), "net_profit", "CHF_m", 2025, SOURCES)
    assert reason == "value_not_in_quote"


def test_unknown_source_is_rejected():
    _, reason = check(raw(source="S9"), "net_profit", "CHF_m", 2025, SOURCES)
    assert reason == "bad_source"


def test_unit_must_fit_the_metric():
    _, reason = check(raw(reported_unit="pct"), "net_profit", "CHF_m", 2025, SOURCES)
    assert reason == "unit_mismatch"


def test_swiss_apostrophes_and_unit_conversion():
    r = raw(value=1010, reported_unit="count", source="S2", quote="Effectif | 1'010")
    fig, reason = check(r, "headcount_fte", "count", 2025, SOURCES)
    assert reason == "ok" and fig.value == 1010
    r = raw(value=107488.9, quote="Total assets | 107,488.9")
    fig, reason = check(r, "total_assets", "CHF_bn", 2025, SOURCES)
    assert reason == "ok" and abs(fig.value - 107.4889) < 1e-9


def test_not_found_is_not_an_error():
    _, reason = check(RawFigure(found=False), "net_profit", "CHF_m", 2025, SOURCES)
    assert reason == "not_found"


def test_to_metric_unit():
    assert to_metric_unit(5_000_000, "CHF", "CHF_m") == 5.0
    assert to_metric_unit(521, "CHF_bn", "CHF_bn") == 521
    assert to_metric_unit(14_558_016, "CHF_k", "CHF_m") == 14_558.016


def test_expenses_are_stored_positive():
    src = {"S1": hit(12, 7, "| Charges d'exploitation | -302'117 |")}
    r = raw(value=-302117, reported_unit="CHF_k", quote="Charges d'exploitation | -302'117")
    fig, reason = check(r, "operating_expenses", "CHF_m", 2025, src)
    assert reason == "ok" and abs(fig.value - 302.117) < 1e-9
