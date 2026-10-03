"""Ablation chunkers built from the cached parses (run after `make ingest`).

  structure_hdr       structure chunks + the same `Bank | Year | Section` header as table_aware
  table_aware_nohdr   table_aware chunks with that header removed (tables still isolated)

Together with the three main chunkers they separate "tables are isolated" from "the chunk text
names its bank and year".
"""

from __future__ import annotations

from finagent.db import pool
from finagent.ingest.chunkers import (
    HEADER_RESERVE,
    MAX_TOKENS,
    chunk_structure,
    chunk_table_aware,
    load_tokenizer,
    with_context_header,
    without_context_header,
)
from finagent.ingest.download import raw_path, read_sources
from finagent.ingest.parse import parse_pdf
from finagent.ingest.run import TS_CONFIG, insert_chunks
from finagent.ingest.text import BANK_NAMES

VARIANTS = ("structure_hdr", "table_aware_nohdr")


def build_variants() -> None:
    tok = load_tokenizer()
    for row in read_sources():
        with pool().connection() as conn:
            doc_id = conn.execute(
                "SELECT doc_id FROM documents WHERE sha256 = %s", (row["sha256"],)
            ).fetchone()[0]
            have = {
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT chunker FROM chunks WHERE doc_id = %s", (doc_id,)
                )
            }
            if set(VARIANTS) <= have:
                print(f"skipped  {raw_path(row).name}", flush=True)
                continue
            blocks = parse_pdf(raw_path(row), doc_id, row["sha256"])
            meta = {"bank": BANK_NAMES[row["bank"]], "year": int(row["year"])}
            ts_chunks = with_context_header(
                chunk_structure(blocks, tok, max_tokens=MAX_TOKENS - HEADER_RESERVE),
                meta,
                "structure_hdr",
            ) + without_context_header(chunk_table_aware(blocks, meta, tok), "table_aware_nohdr")
            with conn.transaction():
                insert_chunks(conn, doc_id, ts_chunks, TS_CONFIG[row["lang"]], tok)
            print(f"built    {raw_path(row).name} (+{len(ts_chunks)} chunks)", flush=True)


if __name__ == "__main__":
    build_variants()
