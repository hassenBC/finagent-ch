import pytest

from eval.dataset_utils import evidence_on_pages, overlap, safe_eval


def test_evidence_found_with_swiss_number_format():
    page = "Net profit\n1’234.5\n2024\nCET1 capital ratio\n19.7"
    assert evidence_on_pages("CET1 capital ratio 19.7", [page])
    assert evidence_on_pages("Net profit 1234.5", [page])


def test_evidence_rejects_missing_number_and_multi_part():
    page = "CET1 capital ratio 19.7"
    assert not evidence_on_pages("CET1 capital ratio 18.7", [page])
    assert not evidence_on_pages("CET1 capital ratio 19.7 || Leverage ratio 5.1", [page])
    assert evidence_on_pages(
        "CET1 capital ratio 19.7 || Leverage ratio 5.1", [page, "Leverage ratio 5.1"]
    )


@pytest.mark.parametrize(
    ("expr", "value"), [("(19.7 - 16.1)", 3.6), ("2 * (3 + 4) / 7", 2.0), ("-5 + 10", 5.0)]
)
def test_safe_eval(expr, value):
    assert safe_eval(expr) == pytest.approx(value)


@pytest.mark.parametrize("bad", ["__import__('os')", "2 ** 3", "abs(-1)", "1; 2"])
def test_safe_eval_rejects_hostile_input(bad):
    with pytest.raises((ValueError, SyntaxError)):
        safe_eval(bad)


def test_overlap_measures_paraphrase():
    ev = "Net new money 12.3"
    assert overlap("What was net new money in 2025?", ev) > overlap(
        "How much did clients bring in?", ev
    )
