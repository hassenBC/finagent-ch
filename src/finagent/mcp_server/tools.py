"""Tool implementations behind the MCP server (Phase 6.2), as plain functions for testing.

Every tool returns {"payload": ..., "_labels": {"sensitivity": ..., "trust": ...}}; the Phase 7
policy engine reads `_labels`. Document text is `untrusted`: anyone who can publish a PDF
controls it.
"""

from __future__ import annotations

import ast
import json
import operator
import os
from functools import lru_cache
from typing import Any

from finagent.db import pool
from finagent.figures.sql_tool import run_figures_query
from finagent.ingest.text import BANK_NAMES

FIGURES_SOURCE = os.environ.get("FINAGENT_FIGURES_SOURCE", "extracted:deepseek_flash")
RETRIEVAL = "configs/retrieval/C_bge_m3_hybrid_filters_translate_tsrank.yaml"
EMAIL_DOMAIN_NOTE = "Mock: the message is stored in an outbox table and never sent."


def labelled(payload: Any, sensitivity: str, trust: str) -> dict:
    return {"payload": payload, "_labels": {"sensitivity": sensitivity, "trust": trust}}


MAX_CHARS = {"query": 1000, "sql": 4000, "client_id": 64, "to": 320, "subject": 300, "body": 20000}


def cap_lengths(**fields: str) -> None:
    """Reject oversized text arguments before any parsing, translation or database access."""
    for name, value in fields.items():
        if len(value) > MAX_CHARS[name]:
            raise ValueError(f"{name} is too long ({len(value)} > {MAX_CHARS[name]} characters)")


# --- calculate -------------------------------------------------------------------------------
class CalcError(ValueError):
    pass


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv}  # fmt: skip
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def calculate_expr(expression: str) -> float:
    """Numbers, + - * /, unary minus and parentheses only — parsed with `ast`, never `eval`."""
    if not expression or len(expression) > 200:
        raise CalcError("expression must be 1-200 characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise CalcError(f"not an arithmetic expression: {e.msg}") from e

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise CalcError("division by zero")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        raise CalcError(f"not allowed: {type(node).__name__}")

    return round(ev(tree), 10)


def calculate(expression: str) -> dict:
    return labelled(calculate_expr(expression), "public", "trusted")


# --- search_documents ------------------------------------------------------------------------
@lru_cache
def _retrieval_cfg():
    from finagent.retrieval.types import RetrievalConfig

    return RetrievalConfig.from_yaml(RETRIEVAL)


@lru_cache
def _docs() -> dict[int, tuple[str, int]]:
    with pool().connection() as conn:
        return {d: (b, y) for d, b, y in conn.execute("SELECT doc_id, bank, year FROM documents")}


def search_documents(query: str, bank: str | None = None, year: int | None = None,
                     k: int = 5) -> dict:  # fmt: skip
    from finagent.retrieval.pipeline import retrieve
    from finagent.retrieval.types import Filters

    cap_lengths(query=query)
    if bank is not None and bank not in BANK_NAMES:
        raise ValueError(f"unknown bank {bank!r}; use one of {sorted(BANK_NAMES)}")
    filters = Filters(banks=[bank] if bank else None, years=[year] if year else None)
    cfg = _retrieval_cfg().model_copy(update={"top_k": max(1, min(k, 10))})
    hits = retrieve(query, cfg, filters if (bank or year) else None)
    if any(h.doc_id not in _docs() for h in hits):  # a document was added after the cache was built
        _docs.cache_clear()
    passages = [
        {"source_id": f"{_docs()[h.doc_id][0]}-{_docs()[h.doc_id][1]}-p{h.page_start}",
         "bank": _docs()[h.doc_id][0], "year": _docs()[h.doc_id][1], "page": h.page_start,
         "text": h.content[:1500]}
        for h in hits
    ]  # fmt: skip
    return labelled(passages, "public", "untrusted")


# --- query_figures ---------------------------------------------------------------------------
def query_figures(sql: str) -> dict:
    cap_lengths(sql=sql)
    r = run_figures_query(sql, source=FIGURES_SOURCE)
    if not r.ok:
        raise ValueError(r.error)
    return labelled({"rows": r.rows, "truncated": r.truncated}, "internal", "trusted")


# --- client notes and e-mail -----------------------------------------------------------------
def read_client_notes(client_id: str) -> dict:
    cap_lengths(client_id=client_id)
    cid = client_id.strip().upper().replace("CLIENT ", "C")
    with pool().connection() as conn:
        row = conn.execute(
            "SELECT client_id, display_name, risk_profile, portfolio_chf, allocation, advisor,"
            " notes FROM client_notes WHERE client_id = %s",
            (cid,),
        ).fetchone()
    if row is None:
        raise ValueError(f"no client {client_id!r} (ids look like C0042)")
    keys = ["client_id", "display_name", "risk_profile", "portfolio_chf", "allocation",
            "advisor", "notes"]  # fmt: skip
    rec = dict(zip(keys, row, strict=True)) | {"portfolio_chf": float(row[3])}
    return labelled(rec, "confidential", "trusted")


def send_email(to: str, subject: str, body: str) -> dict:
    cap_lengths(to=to, subject=subject, body=body)
    trace = os.environ.get("FINAGENT_TRACE_ID")
    with pool().connection() as conn:
        (eid,) = conn.execute(
            "INSERT INTO outbox (trace_id, to_addr, subject, body) VALUES (%s, %s, %s, %s)"
            " RETURNING email_id",
            (trace, to, subject, body),
        ).fetchone()
    return labelled({"status": "queued", "email_id": eid, "note": EMAIL_DOMAIN_NOTE},
                    "public", "trusted")  # fmt: skip


def dumps(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)
