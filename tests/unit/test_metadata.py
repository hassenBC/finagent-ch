import pytest

from finagent.retrieval.metadata import extract_filters


@pytest.mark.parametrize(
    ("q", "banks", "years"),
    [
        ("What was Vontobel's CET1 ratio at the end of 2025?", ["vontobel"], [2025]),
        ("Quel est le résultat net de la BCV en 2025 ?", ["bcv"], [2025]),
        ("Julius Baer net new money 2024 vs 2025", ["juliusbaer"], [2024, 2025]),
        (
            "In Swissquote's 2024 report, the position as at 31 December 2023?",
            ["swissquote"],
            [2024],
        ),
        ("Which is higher, EFG or Swissquote?", ["efg", "swissquote"], None),
        ("What is the interest rate shock?", None, None),
    ],
)
def test_extract_filters(q, banks, years):
    f = extract_filters(q)
    if banks is None and years is None:
        assert f is None
    else:
        assert f.banks == banks and f.years == years
