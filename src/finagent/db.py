"""Connection pool and a minimal migration runner (applies sql/*.sql in order, once)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from finagent.config import ROOT, env

SQL_DIR = ROOT / "sql"


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)


@lru_cache
def pool() -> ConnectionPool:
    # Only valid after migrate(): register_vector needs the extension to exist.
    return ConnectionPool(
        env().database_url, min_size=1, max_size=8, configure=_configure, open=True
    )


def migrate(url: str | None = None, sql_dir: Path = SQL_DIR) -> list[str]:
    """Apply pending migrations; return the filenames applied this time."""
    applied_now: list[str] = []
    with psycopg.connect(url or env().database_url, autocommit=True) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   filename   TEXT PRIMARY KEY,
                   applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
        )
        done = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
        for path in sorted(sql_dir.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())  # no params -> multi-statement allowed
                conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
            applied_now.append(path.name)
    return applied_now


if __name__ == "__main__":
    applied = migrate()
    print(f"applied: {', '.join(applied)}" if applied else "up to date")
