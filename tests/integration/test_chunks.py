import psycopg
import pytest

from finagent.config import env

pytestmark = pytest.mark.integration

# multilingual-e5 truncates at 512 tokens; 505 leaves room for special tokens and "passage: ".
LIMIT = 505


@pytest.fixture(scope="module")
def conn():
    try:
        c = psycopg.connect(env().database_url, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (make db-up)")
    n = c.execute("SELECT count(*) FROM chunks").fetchone()[0]
    if n == 0:
        pytest.skip("no chunks ingested (make ingest)")
    yield c
    c.close()


def test_no_chunk_over_token_limit(conn):
    rows = conn.execute(
        "SELECT chunker, max(n_tokens) FROM chunks GROUP BY chunker HAVING max(n_tokens) > %s",
        (LIMIT,),
    ).fetchall()
    assert rows == []


def test_all_chunkers_present_and_pages_valid(conn):
    chunkers = {r[0] for r in conn.execute("SELECT DISTINCT chunker FROM chunks")}
    main = {"fixed512", "structure", "table_aware"}
    variants = {"structure_hdr", "table_aware_nohdr"}  # ablations, see ingest/variants.py
    assert main <= chunkers <= main | variants
    bad = conn.execute(
        """SELECT count(*) FROM chunks c JOIN documents d USING (doc_id)
           WHERE c.page_start < 1 OR c.page_end > d.n_pages OR c.page_start > c.page_end"""
    ).fetchone()[0]
    assert bad == 0
