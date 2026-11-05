import psycopg
import pytest

from finagent.config import env
from finagent.db import migrate

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def url():
    url = env().database_url
    try:
        psycopg.connect(url, connect_timeout=2).close()
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (make db-up)")
    return url


def test_migrate_is_idempotent(url):
    migrate(url)
    assert migrate(url) == []


def test_schema_and_pgvector_present(url):
    migrate(url)
    with psycopg.connect(url) as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        }
        assert {
            "documents",
            "pages",
            "chunks",
            "figures",
            "eval_runs",
            "eval_results",
            "traces",
            "tool_calls",
            "schema_migrations",
        } <= tables
        assert conn.execute("SELECT '[1,2,3]'::vector <=> '[1,2,3]'::vector").fetchone()[0] == 0
