"""Layer 2 alone: the agent_reader role must refuse writes, other tables and long queries even
when the parser layer is bypassed (raw SQL sent straight to the database)."""

import time

import psycopg
import pytest

from finagent.config import env
from finagent.figures.sql_tool import run_figures_query

pytestmark = pytest.mark.integration


@pytest.fixture
def conn():
    try:
        c = psycopg.connect(env().agent_database_url, connect_timeout=2, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("Postgres or agent_reader role not available (make db-up migrate)")
    yield c
    c.close()


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM figures",
        "UPDATE figures SET value = 0",
        "INSERT INTO documents (bank, year, doc_type, lang, sha256) VALUES ('x', 1, 'x', 'x', 'x')",
        "DROP TABLE figures",
        "CREATE TABLE stolen (a int)",
        "SELECT * FROM chunks LIMIT 1",
        "SELECT * FROM eval_runs LIMIT 1",
        "SELECT * FROM pg_authid",
        "SET default_transaction_read_only = off; DELETE FROM figures",
    ],
)
def test_role_refuses(conn, sql):
    with pytest.raises(psycopg.Error):
        conn.execute(sql)


def test_role_times_out_long_queries(conn):
    start = time.perf_counter()
    with pytest.raises(psycopg.errors.QueryCanceled):
        conn.execute("SELECT pg_sleep(10)")
    assert time.perf_counter() - start < 5


def test_role_can_read_figures_and_documents(conn):
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] > 0
    conn.execute("SELECT count(*) FROM figures").fetchone()


def test_tool_end_to_end():
    r = run_figures_query("SELECT bank, year FROM documents ORDER BY bank, year")
    if not r.ok and "database error" in (r.error or ""):
        pytest.skip(r.error)
    assert r.ok and len(r.rows) == 12 and r.executed_sql.endswith("LIMIT 200")
    bad = run_figures_query("SELECT pg_sleep(10)")
    assert not bad.ok and bad.error.startswith("rejected")
