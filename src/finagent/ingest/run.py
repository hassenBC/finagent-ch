"""Idempotent ingestion: sources.csv -> documents, pages, chunks (all chunkers) in Postgres."""

from __future__ import annotations

import psycopg

from finagent.db import migrate, pool
from finagent.ingest.chunkers import (
    chunk_fixed,
    chunk_structure,
    chunk_table_aware,
    load_tokenizer,
)
from finagent.ingest.download import raw_path, read_sources
from finagent.ingest.parse import page_texts, parse_pdf
from finagent.ingest.text import BANK_NAMES, normalise_numbers

TS_CONFIG = {"en": "english", "fr": "french", "de": "german"}


def _insert_document(conn: psycopg.Connection, row: dict[str, str], n_pages: int) -> int:
    return conn.execute(
        """INSERT INTO documents (bank, year, doc_type, lang, title, source_url, sha256, n_pages)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING doc_id""",
        (
            row["bank"],
            int(row["year"]),
            row["doc_type"],
            row["lang"],
            f"{BANK_NAMES[row['bank']]} {row['doc_type'].replace('_', ' ')} {row['year']}",
            row["url"],
            row["sha256"],
            n_pages,
        ),
    ).fetchone()[0]


def insert_chunks(conn: psycopg.Connection, doc_id: int, chunks: list, ts: str, tok) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO chunks (doc_id, chunker, page_start, page_end, section_path,
                                   kind, content, n_tokens, ts_config, tsv)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::regconfig,
                       to_tsvector(%s::regconfig, %s))""",
            [
                (
                    doc_id,
                    c.chunker,
                    c.page_start,
                    c.page_end,
                    c.section_path,
                    c.kind,
                    c.content,
                    len(tok.encode(c.content)),
                    ts,
                    ts,
                    normalise_numbers(c.content),
                )
                for c in chunks
            ],
        )


def ingest_document(row: dict[str, str], tok) -> bool:
    """Ingest one PDF; return False if it was already present."""
    with pool().connection() as conn:
        if conn.execute("SELECT 1 FROM documents WHERE sha256 = %s", (row["sha256"],)).fetchone():
            return False
        path = raw_path(row)
        pages = page_texts(path)
        with conn.transaction():
            doc_id = _insert_document(conn, row, len(pages))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO pages (doc_id, page_no, text) VALUES (%s, %s, %s)",
                    [(doc_id, i, t) for i, t in enumerate(pages, 1)],
                )
            blocks = parse_pdf(path, doc_id, row["sha256"])
            meta = {"bank": BANK_NAMES[row["bank"]], "year": int(row["year"])}
            chunks = (
                chunk_fixed(blocks, tok)
                + chunk_structure(blocks, tok)
                + chunk_table_aware(blocks, meta, tok)
            )
            insert_chunks(conn, doc_id, chunks, TS_CONFIG[row["lang"]], tok)
    return True


def ingest_all() -> None:
    migrate()
    tok = load_tokenizer()
    for row in read_sources():
        done = ingest_document(row, tok)
        print(f"{'ingested' if done else 'skipped '} {raw_path(row).name}", flush=True)


if __name__ == "__main__":
    ingest_all()
