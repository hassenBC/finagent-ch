"""Plant and remove the Phase 7 attacks in the database.

Document attacks become synthetic `documents` rows (doc_type 'synthetic_injection') with one
table-aware chunk each, embedded with bge-m3 and indexed for FTS like every other chunk, so the
normal retrieval path finds them. Client-note attacks rewrite note fields. `planted()` restores
everything on exit, also after a crash; `cleanup()` removes leftovers from an interrupted run.
Start the MCP server only after planting: the server caches document metadata.
"""

from __future__ import annotations

from contextlib import contextmanager

from finagent.clients import make_clients
from finagent.db import pool
from finagent.ingest.embed import EMBEDDERS, _encode
from finagent.ingest.text import BANK_NAMES, normalise_numbers
from finagent.retrieval.expand import BANK_LANG

DOC_TYPE = "synthetic_injection"


def cleanup() -> None:
    originals = {c["client_id"]: c["notes"] for c in make_clients()}
    with pool().connection() as conn, conn.transaction():
        conn.execute("DELETE FROM documents WHERE doc_type = %s", (DOC_TYPE,))  # cascades
        for cid, notes in originals.items():
            conn.execute("UPDATE client_notes SET notes = %s WHERE client_id = %s", (notes, cid))


def plant(cases: list[dict]) -> int:
    docs = [c for c in cases if c["planted"]["type"] == "doc"]
    contents = []
    for c in docs:
        p = c["planted"]
        contents.append(
            f"Bank: {BANK_NAMES[p['bank']]} | Year: {p['year']} | "
            f"Section: {p['section']}\n{p['text']}"
        )
    _, _, prefix, _ = EMBEDDERS["bge_m3"]
    vecs = _encode("bge_m3", contents, prefix, 8) if contents else []
    with pool().connection() as conn, conn.transaction():
        for c, content, vec in zip(docs, contents, vecs, strict=True):
            p = c["planted"]
            lang = BANK_LANG.get(p["bank"], "en")
            ts = "french" if lang == "fr" else "english"
            (doc_id,) = conn.execute(
                "INSERT INTO documents (bank, year, doc_type, lang, title, sha256, n_pages)"
                " VALUES (%s, %s, %s, %s, %s, %s, 1) RETURNING doc_id",
                (
                    p["bank"],
                    p["year"],
                    DOC_TYPE,
                    lang,
                    f"Synthetic test page ({c['id']})",
                    f"synthetic-injection-{c['id']}",
                ),
            ).fetchone()
            (chunk_id,) = conn.execute(
                "INSERT INTO chunks (doc_id, chunker, page_start, page_end, section_path, kind,"
                " content, n_tokens, ts_config, tsv) VALUES (%s, 'table_aware', 1, 1, %s, 'text',"
                " %s, %s, %s::regconfig, to_tsvector(%s::regconfig, %s)) RETURNING chunk_id",
                (
                    doc_id,
                    p["section"],
                    content,
                    len(content.split()),
                    ts,
                    ts,
                    normalise_numbers(content),
                ),
            ).fetchone()
            conn.execute(
                "INSERT INTO emb_bge_m3 (chunk_id, embedding) VALUES (%s, %s)", (chunk_id, vec)
            )
        for c in cases:
            if c["planted"]["type"] == "note":
                conn.execute(
                    "UPDATE client_notes SET notes = %s WHERE client_id = %s",
                    (c["planted"]["text"], c["planted"]["client_id"]),
                )
    return len(docs)


@contextmanager
def planted(cases: list[dict]):
    cleanup()
    n = plant(cases)
    try:
        yield n
    finally:
        cleanup()
