"""Fast-tier CI fixture (Phase 8.2): 4 reports' table-aware chunks for e5-small retrieval.

python -m eval.ci_fixture build   (from the full local DB) -> tests/fixtures/ci_fixture.jsonl.gz,
                                  eval/datasets/qa_ci.jsonl and its config CI_e5_small_hybrid.yaml
python -m eval.ci_fixture load    (into $DATABASE_URL, after migrations; used by GitHub Actions)
The fixture holds only what retrieval needs: the FTS vector (stemmed lexemes), the e5-small
embedding and the page range of each chunk. The report text itself is NOT stored — chunk content
is a placeholder — so the fixture does not redistribute the banks' reports.
"""

from __future__ import annotations

import gzip
import json
import sys

from finagent.config import ROOT
from finagent.db import pool

FIXTURE = ROOT / "tests/fixtures/ci_fixture.jsonl.gz"
SUBSET = ROOT / "eval/datasets/qa_ci.jsonl"
CONFIG = ROOT / "configs/retrieval/CI_e5_small_hybrid.yaml"
DOCS = [("efg", 2024), ("efg", 2025), ("vontobel", 2025), ("juliusbaer", 2025)]
PLACEHOLDER = "[report text not redistributed: {bank} {year}, page {page}]"


def build() -> None:
    with pool().connection() as conn:
        docs = conn.execute(
            "SELECT doc_id, bank, year, doc_type, lang, title, sha256, n_pages FROM documents "
            "WHERE doc_type = 'annual_report' AND (bank, year) IN "
            "(SELECT * FROM unnest(%s::text[], %s::int[]))",
            ([b for b, _ in DOCS], [y for _, y in DOCS]),
        ).fetchall()
        ids = [d[0] for d in docs]
        chunks = conn.execute(
            "SELECT c.chunk_id, c.doc_id, c.page_start, c.page_end, c.kind, c.n_tokens,"
            " c.ts_config::text, c.tsv::text, e.embedding::text FROM chunks c"
            " JOIN emb_e5_small e USING (chunk_id)"
            " WHERE c.doc_id = ANY(%s) AND c.chunker = 'table_aware' ORDER BY c.chunk_id",
            (ids,),
        ).fetchall()
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(FIXTURE, "wt") as f:
        for d in docs:
            f.write(json.dumps({"t": "doc", "row": list(d)}) + "\n")
        for cid, did, p0, p1, kind, ntok, tsc, tsv, emb in chunks:
            vec = [round(x, 5) for x in json.loads(emb)]
            f.write(
                json.dumps(
                    {"t": "chunk", "row": [cid, did, p0, p1, kind, ntok, tsc, tsv], "emb": vec}
                )
                + "\n"
            )
    shas = {d[6] for d in docs}
    items = [json.loads(x) for x in (ROOT / "eval/datasets/qa_dev.jsonl").read_text().splitlines()]
    keep = [
        i
        for i in items
        if i["answerable"]
        and {g["sha256"] for g in i["gold_pages"] + i.get("alt_pages", [])} <= shas
    ]
    SUBSET.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in keep))
    CONFIG.write_text(
        "# Fast CI tier: e5-small hybrid on the 4-document fixture (no GPU, no API key)\n"
        "name: CI_e5_small_hybrid\nchunker: table_aware\nembedding_model: e5_small\n"
        "retrieval: hybrid\nuse_metadata_filters: true\nfts: {rank: plain, normalization: 1}\n"
        "translate_cross_lingual: false\ntop_k: 10\ndataset: eval/datasets/qa_ci.jsonl\n"
    )
    print(
        f"{len(docs)} docs, {len(chunks)} chunks -> {FIXTURE.name} "
        f"({FIXTURE.stat().st_size / 1e6:.1f} MB); {len(keep)} questions -> {SUBSET.name}"
    )


def load() -> None:
    with gzip.open(FIXTURE, "rt") as f:
        rows = [json.loads(x) for x in f]
    docs = [r["row"] for r in rows if r["t"] == "doc"]
    chunks = [r for r in rows if r["t"] == "chunk"]
    bank_year = {d[0]: (d[1], d[2]) for d in docs}
    dim = len(chunks[0]["emb"])
    with pool().connection() as conn, conn.transaction():
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS emb_e5_small (chunk_id BIGINT PRIMARY KEY REFERENCES"
            f" chunks ON DELETE CASCADE, embedding VECTOR({dim}) NOT NULL)"
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO documents (doc_id, bank, year, doc_type, lang, title, sha256, n_pages)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                docs,
            )
            cur.executemany(
                "INSERT INTO chunks (chunk_id, doc_id, chunker, page_start, page_end, kind,"
                " content, n_tokens, ts_config, tsv) VALUES (%s, %s, 'table_aware', %s, %s, %s,"
                " %s, %s, %s::regconfig, %s::tsvector)",
                [
                    (
                        c["row"][0],
                        c["row"][1],
                        c["row"][2],
                        c["row"][3],
                        c["row"][4],
                        PLACEHOLDER.format(
                            bank=bank_year[c["row"][1]][0],
                            year=bank_year[c["row"][1]][1],
                            page=c["row"][2],
                        ),
                        c["row"][5],
                        c["row"][6],
                        c["row"][7],
                    )
                    for c in chunks
                ],
            )
            cur.executemany(
                "INSERT INTO emb_e5_small (chunk_id, embedding) VALUES (%s, %s)",
                [(c["row"][0], str(c["emb"])) for c in chunks],
            )
        conn.execute("SELECT setval('documents_doc_id_seq', (SELECT max(doc_id) FROM documents))")
        conn.execute("SELECT setval('chunks_chunk_id_seq', (SELECT max(chunk_id) FROM chunks))")
    print(f"loaded {len(docs)} documents, {len(chunks)} chunks")


if __name__ == "__main__":
    {"build": build, "load": load}[sys.argv[1]]()
