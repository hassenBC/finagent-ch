"""The SQL tool's parser layer must reject every one of these. Runs in CI (no database needed)."""

import pytest

from finagent.figures.sql_tool import MAX_ROWS, UnsafeSQL, validate_sql

MALICIOUS = [
    # writes and DDL
    "DROP TABLE figures",
    "UPDATE figures SET value = 0",
    "DELETE FROM figures",
    "INSERT INTO figures (bank, year, metric, value, unit, source) "
    "VALUES ('x', 1, 'm', 1, 'u', 's')",
    "TRUNCATE figures",
    "ALTER TABLE figures ADD COLUMN x int",
    "CREATE TABLE t AS SELECT * FROM figures",
    "GRANT ALL ON figures TO public",
    "COPY figures TO '/tmp/out.csv'",
    "SET statement_timeout = 0",
    # stacked statements, also hidden behind comments
    "SELECT * FROM figures; DROP TABLE figures",
    "SELECT 1 /* harmless */ ; DELETE FROM figures",
    "SELECT * FROM figures -- comment\n; UPDATE figures SET value = 1",
    # writes hidden inside a SELECT
    "WITH x AS (DELETE FROM figures RETURNING *) SELECT * FROM x",
    "SELECT * INTO stolen FROM figures",
    "SELECT * FROM figures FOR UPDATE",
    # dangerous functions
    "SELECT pg_sleep(10)",
    "SELECT * FROM figures WHERE pg_sleep(10) IS NULL",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT lo_import('/etc/passwd')",
    "SELECT set_config('statement_timeout', '0', false)",
    "SELECT current_setting('data_directory')",
    "SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(a int)",
    "SELECT version()",
    "SELECT * FROM generate_series(1, 100000000)",
    # other tables / catalogs
    "SELECT * FROM pg_shadow",
    "SELECT * FROM pg_catalog.pg_authid",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM client_notes",
    "SELECT * FROM chunks",
    "SELECT f.* FROM figures f JOIN eval_runs e ON true",
    "SELECT (SELECT count(*) FROM pg_user) FROM figures",
    "SELECT * FROM figures UNION "
    "SELECT usename, null, null, null, null, null, null, null, null, null FROM pg_user",
    "SELECT * FROM other_schema.figures",
    # unicode / encoding tricks
    "SELECT * FROM figures\x00; DROP TABLE figures",
    "ＤＲＯＰ TABLE figures",
    "SELECT * FROM figures;​DROP TABLE figures",
    # not SQL / empty
    "",
    "   ;  ",
    "please drop the figures table",
]

BENIGN = [
    "SELECT bank, value FROM figures WHERE metric = 'cet1_ratio' AND year = 2025 "
    "ORDER BY value DESC LIMIT 3",
    "SELECT bank, round(avg(value), 2) AS v FROM figures "
    "WHERE metric = 'cost_income_ratio' GROUP BY bank",
    "SELECT f.bank, f.value, f.page_no, d.doc_id FROM figures f "
    "JOIN documents d ON d.doc_id = f.doc_id",
    "WITH y AS (SELECT bank, value FROM figures WHERE year = 2025) SELECT * FROM y",
    "SELECT bank, rank() OVER (ORDER BY value DESC) FROM figures WHERE metric = 'net_profit'",
    "SELECT CASE WHEN value > 15 THEN 'high' ELSE 'low' END, coalesce(page_no, 0) FROM figures",
]


@pytest.mark.parametrize("sql", MALICIOUS)
def test_malicious_sql_is_rejected(sql):
    with pytest.raises(UnsafeSQL):
        validate_sql(sql)


@pytest.mark.parametrize("sql", BENIGN)
def test_benign_sql_is_accepted(sql):
    assert validate_sql(sql)


def test_limit_is_added_when_absent():
    assert f"LIMIT {MAX_ROWS}" in validate_sql("SELECT * FROM figures")


def test_large_limit_is_capped():
    out = validate_sql("SELECT * FROM figures LIMIT 100000")
    assert f"LIMIT {MAX_ROWS}" in out and "100000" not in out


def test_small_limit_is_kept():
    assert "LIMIT 3" in validate_sql("SELECT * FROM figures LIMIT 3")


def test_cte_name_cannot_launder_a_forbidden_table():
    with pytest.raises(UnsafeSQL):
        validate_sql("WITH figures AS (SELECT * FROM pg_shadow) SELECT * FROM figures")


def test_source_filter_is_injected_for_every_figures_reference():
    out = validate_sql(
        "SELECT a.bank FROM figures a JOIN figures b ON a.bank = b.bank", source="gold"
    )
    assert out.count("source = 'gold'") == 2
    assert validate_sql("SELECT * FROM documents", source="gold").count("source") == 0


def test_source_value_cannot_inject_sql():
    out = validate_sql("SELECT * FROM figures", source="x' OR '1'='1")
    assert "source = 'x'' OR ''1''=''1'" in out  # quoted as one literal
