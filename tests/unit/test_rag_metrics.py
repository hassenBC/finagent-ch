import pytest

from eval.rag_metrics import abstention_scores, citation_scores, numbers_in, numeric_match


def G(value, unit, tol):
    return {"value": value, "unit": unit, "tolerance": tol}


@pytest.mark.parametrize(
    ("answer", "gold"),
    [
        ("The CET1 ratio was 19.7% at 31 December 2025 [S1].", G(19.7, "pct", 0.05)),
        ("Le ratio CET1 s'élevait à 19,7 % au 31.12.2025.", G(19.7, "pct", 0.05)),
        ("Net profit was CHF 1’234.5 million in 2024.", G(1234.5, "CHF_m", 1.2)),
        ("AuM reached CHF 241 billion.", G(241000, "CHF_m", 241)),
        ("Total: CHF 7,918,168 [S2].", G(7918168, "CHF", 7918)),
        ("Total assets were CHF 13,290,010,856.", G(13290.0, "CHF_m", 13.3)),
        ("CHF 30,064 thousand.", G(30.064, "CHF_m", 0.03)),
        ("Il a tenu 25 séances ordinaires en 2025.", G(25, "count", 0.5)),
    ],
)
def test_numeric_match_handles_formats_and_scales(answer, gold):
    assert numeric_match(answer, gold)["em_any"] == 1.0


def test_numeric_match_first_vs_any_and_misses():
    ans = (
        "Julius Baer: CHF 763.7 million vs Swissquote CHF 366.4 million, "
        "a difference of CHF 397.3 million."
    )
    m = numeric_match(ans, G(397.3, "CHF_m", 0.4))
    assert m == {"em_first": 0.0, "em_any": 1.0}
    assert numeric_match("CET1 was 18.7%.", G(19.7, "pct", 0.05))["em_any"] == 0.0
    assert numeric_match("The sources do not say.", G(19.7, "pct", 0.05))["em_any"] == 0.0


def test_dates_years_and_citations_are_not_numbers():
    assert numbers_in("At 31 December 2025 and 31.12.2024 [S3] it was 5%") == [(5.0, "%")]


def test_citation_scores():
    relevant = {(1, 48)}
    texts = {(1, 50): "CET1 capital ratio 19.7", (1, 60): "other"}
    out = citation_scores(
        [(1, 47, 48), (1, 50, 50), (1, 60, 60)], relevant, texts, "CET1 capital ratio 19.7"
    )
    assert out == [True, True, False]


def test_abstention_scores():
    rows = [
        {"answerable": a, "abstain": b}
        for a, b in [(False, True), (False, False), (True, True), (True, False)]
    ]
    s = abstention_scores(rows)
    assert s["abstain_precision"] == 0.5 and s["abstain_recall"] == 0.5
    assert s["false_abstention_rate"] == 0.5
