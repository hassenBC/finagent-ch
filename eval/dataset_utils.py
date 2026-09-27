"""Shared helpers for building and validating the QA dataset."""

from __future__ import annotations

import ast
import operator
import re

from finagent.ingest.text import normalise_numbers

EVIDENCE_SEP = " || "
_WORD = re.compile(r"[A-Za-zÀ-ÿ]{3,}|\d+(?:\.\d+)?")
_NUM = re.compile(r"\d+(?:\.\d+)?")


def tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD.findall(normalise_numbers(text))}


def numbers(text: str) -> set[float]:
    return {float(n) for n in _NUM.findall(normalise_numbers(text))}


def evidence_on_pages(evidence: str, page_texts: list[str], coverage: float = 0.9) -> bool:
    """True if every ' || '-separated evidence part is (nearly) contained in one gold page.

    PDF text extraction puts table cells on separate lines, so contiguous substring matching is
    too strict; we require that >= `coverage` of the evidence's words and numbers occur on a page.
    """
    page_tokens = [tokens(t) for t in page_texts]
    for part in evidence.split(EVIDENCE_SEP):
        want = tokens(part)
        if not want:
            return False
        if not any(len(want & pt) / len(want) >= coverage for pt in page_tokens):
            return False
    return True


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def safe_eval(expr: str) -> float:
    """Evaluate +,-,*,/ and parentheses over numbers; never uses eval()."""

    def walk(n: ast.AST) -> float:
        if isinstance(n, ast.Expression):
            return walk(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, int | float):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](walk(n.left), walk(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -walk(n.operand)
        raise ValueError(f"unsupported expression: {expr!r}")

    return walk(ast.parse(expr, mode="eval"))


def overlap(question: str, evidence: str) -> float:
    """Share of the question's content words that also occur in the evidence."""
    q = tokens(question)
    return len(q & tokens(evidence)) / len(q) if q else 0.0


def find_alt_pages(
    evidence: str, doc_pages: dict[int, str], gold: set[int], coverage: float = 0.9
) -> list[int]:
    """Other pages of the same document that also contain this evidence part.

    A fact repeated elsewhere (opening/closing balances, key-figures page, mission statements)
    is an equally valid retrieval target, so it must not be counted as a miss. Evidence with
    fewer than 4 distinct words is too generic to match safely and gets no alternates.
    """
    want = tokens(evidence)
    if len(want) < 4:
        return []
    return sorted(
        pn
        for pn, text in doc_pages.items()
        if pn not in gold and len(want & tokens(text)) / len(want) >= coverage
    )
