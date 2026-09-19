import pytest

from finagent.ingest.text import normalise_numbers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CHF 1’234.5 million", "CHF 1234.5 million"),
        ("Total assets 61'620", "Total assets 61620"),
        ("Bénéfice net 1 234,5 millions", "Bénéfice net 1234.5 millions"),
        ("Fonds propres 12 345 678 CHF", "Fonds propres 12345678 CHF"),
        ("CET1 ratio 19.1%", "CET1 ratio 19.1%"),
        ("ratio CET1 de 19,1 %", "ratio CET1 de 19.1 %"),
        ("AuM of 1,234.5 billion", "AuM of 1234.5 billion"),
        ("revenue 12,345,678", "revenue 12345678"),
        ("in 2024 100 clients", "in 2024 100 clients"),
        ("2024 2025 2026", "2024 2025 2026"),
        ("1’234’567", "1234567"),
        ("(1’234)", "(1234)"),
    ],
)
def test_normalise_numbers(raw, expected):
    assert normalise_numbers(raw) == expected
