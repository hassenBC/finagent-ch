"""Text helpers shared by ingestion and retrieval."""

from __future__ import annotations

import re

_APOSTROPHE = re.compile(r"(?<=\d)['’ʼ´‘](?=\d{3}(?!\d))")
_SPACE_GROUPS = re.compile(r"(?<![\d.,])(\d{1,3})((?:[    ]\d{3}(?!\d))+)")
_COMMA_GROUPS = re.compile(r"(?<![\d.,])(\d{1,3})((?:,\d{3}(?!\d))+)")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def normalise_numbers(text: str) -> str:
    """Rewrite numbers to a plain form: ``1’234.5`` / ``1 234,5`` / ``1,234.5`` -> ``1234.5``.

    Used for the full-text index and for evidence matching; the original text is kept for display.
    """
    text = _APOSTROPHE.sub("", text)
    text = _SPACE_GROUPS.sub(lambda m: m.group(1) + re.sub(r"\D", "", m.group(2)), text)
    text = _COMMA_GROUPS.sub(lambda m: m.group(1) + m.group(2).replace(",", ""), text)
    return _DECIMAL_COMMA.sub(".", text)


BANK_NAMES = {
    "juliusbaer": "Julius Baer",
    "vontobel": "Vontobel",
    "efg": "EFG International",
    "swissquote": "Swissquote",
    "bcv": "BCV",
    "bcge": "BCGE",
}
