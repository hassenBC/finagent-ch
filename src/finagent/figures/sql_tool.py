"""Read-only SQL over the `figures` and `documents` tables, for the agent (Phase 5.4).

Defence in depth — each layer would stop most attacks alone:
1. Parser (`validate_sql`): one SELECT statement, only allowlisted tables and functions, no write or
   lock clauses, no control/format characters; the SQL that runs is regenerated from the parse tree,
   with a LIMIT of at most MAX_ROWS.
2. Database role `agent_reader` (sql/004): SELECT on two tables only, read-only transactions,
   2 s statement timeout.
3. Result size: at most MAX_ROWS rows are fetched.
"""

from __future__ import annotations

import unicodedata
from decimal import Decimal

import psycopg
import sqlglot
from psycopg.rows import dict_row
from pydantic import BaseModel
from sqlglot import exp

from finagent.config import env

MAX_ROWS = 200
ALLOWED_TABLES = {"figures", "documents"}

# Allowlist, not denylist: anything else (pg_sleep, pg_read_file, dblink, lo_import, set_config,
# current_setting, version, generate_series, ...) is rejected without having to be named.
ALLOWED_FUNCS = tuple(
    getattr(exp, n)
    for n in [
        "Count",
        "Sum",
        "Avg",
        "Min",
        "Max",
        "Round",
        "Abs",
        "Floor",
        "Ceil",
        "Sqrt",
        "Pow",
        "Ln",
        "Log",
        "Exp",
        "Stddev",
        "StddevPop",
        "StddevSamp",
        "Variance",
        "Coalesce",
        "Nullif",
        "Greatest",
        "Least",
        "Cast",
        "TryCast",
        "Case",
        "If",
        "Lower",
        "Upper",
        "Trim",
        "Length",
        "Concat",
        "Substring",
        "RowNumber",
        "Rank",
        "DenseRank",
        "Lag",
        "Lead",
        "FirstValue",
        "LastValue",
        "And",
        "Or",
        "Exists",
        "ArrayAgg",
        "GroupConcat",
    ]
    if hasattr(exp, n)
)
FORBIDDEN_NODES = tuple(
    getattr(exp, n)
    for n in [
        "Insert",
        "Update",
        "Delete",
        "Drop",
        "Create",
        "Alter",
        "AlterTable",
        "Command",
        "Merge",
        "TruncateTable",
        "Copy",
        "Into",
        "Lock",
        "Set",
        "Grant",
        "Revoke",
        "Pragma",
        "Use",
        "Transaction",
        "Commit",
        "Rollback",
    ]
    if hasattr(exp, n)
)


class UnsafeSQL(ValueError):
    pass


class SQLResult(BaseModel):
    ok: bool
    rows: list[dict] = []
    error: str | None = None
    executed_sql: str | None = None
    truncated: bool = False


def _check_text(sql: str) -> None:
    for ch in sql:
        if ch in "\n\r\t":
            continue
        if unicodedata.category(ch) in ("Cc", "Cf"):  # control chars, zero-width and bidi marks
            raise UnsafeSQL(f"control or format character U+{ord(ch):04X}")
    if unicodedata.normalize("NFKC", sql) != sql:  # full-width letters and other look-alikes
        raise UnsafeSQL("non-normalised unicode")


def _visible_ctes(table: exp.Table) -> set[str]:
    """CTE names a table reference may use: those attached to a query that encloses it.

    A CTE defined in a sibling or inner subquery does not make an outer reference to the same
    name legitimate (it would still read the real relation, e.g. a catalog table)."""
    names: set[str] = set()
    node = table.parent
    while node is not None:
        with_ = node.args.get("with_") or node.args.get("with")
        if with_ is not None:
            names |= {c.alias_or_name.lower() for c in with_.expressions}
        node = node.parent
    return names


def validate_sql(sql: str, source: str | None = None) -> str:
    """Return the safe SQL to execute, or raise UnsafeSQL.

    With `source`, every reference to `figures` becomes a subquery restricted to that source
    ('gold' or 'extracted:<model>'), so the caller cannot mix or forget sources."""
    _check_text(sql)
    try:
        trees = [t for t in sqlglot.parse(sql, read="postgres") if t is not None]
    except sqlglot.errors.SqlglotError as e:
        raise UnsafeSQL(f"cannot parse: {e}") from e
    if len(trees) != 1:
        raise UnsafeSQL(f"expected exactly one statement, got {len(trees)}")
    tree = trees[0]
    if not isinstance(tree, exp.Select | exp.SetOperation):
        raise UnsafeSQL(f"only SELECT is allowed, got {type(tree).__name__}")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeSQL(f"forbidden clause: {type(node).__name__}")
        if isinstance(node, exp.Func) and not isinstance(node, ALLOWED_FUNCS):
            name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            raise UnsafeSQL(f"function not allowed: {name}")

    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    if ctes & ALLOWED_TABLES:
        raise UnsafeSQL("a CTE may not shadow a table name")
    if any(w.args.get("recursive") for w in tree.find_all(exp.With)):
        raise UnsafeSQL("recursive CTEs are not allowed")  # unbounded work inside one statement
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if t.args.get("catalog") or (t.db and t.db.lower() != "public"):
            raise UnsafeSQL(f"schema-qualified table not allowed: {t.sql()}")
        if name not in ALLOWED_TABLES and name not in _visible_ctes(t):
            raise UnsafeSQL(f"table not allowed: {name}")

    if source is not None:
        for t in [t for t in tree.find_all(exp.Table) if t.name.lower() == "figures"]:
            only = (
                exp.select("*")
                .from_("figures")
                .where(exp.EQ(this=exp.column("source"), expression=exp.Literal.string(source)))
            )
            t.replace(only.subquery(t.alias or "figures"))

    limit = tree.args.get("limit")
    value = limit.expression if isinstance(limit, exp.Limit) else None
    if not (isinstance(value, exp.Literal) and value.is_int and int(value.name) <= MAX_ROWS):
        tree = tree.limit(MAX_ROWS)
    return tree.sql(dialect="postgres")


def _jsonable(v):
    return float(v) if isinstance(v, Decimal) else v


def run_figures_query(sql: str, source: str | None = None, url: str | None = None) -> SQLResult:
    try:
        safe = validate_sql(sql, source)
    except UnsafeSQL as e:
        return SQLResult(ok=False, error=f"rejected: {e}")
    try:
        with psycopg.connect(url or env().agent_database_url, row_factory=dict_row) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(safe)
                rows = cur.fetchmany(MAX_ROWS + 1)
    except psycopg.Error as e:
        return SQLResult(ok=False, error=f"database error: {e}".strip(), executed_sql=safe)
    return SQLResult(
        ok=True,
        rows=[{k: _jsonable(v) for k, v in r.items()} for r in rows[:MAX_ROWS]],
        executed_sql=safe,
        truncated=len(rows) > MAX_ROWS,
    )


SCHEMA = """\
figures(bank TEXT, year INT, metric TEXT, value NUMERIC, unit TEXT, doc_id INT,
        page_no INT)
documents(doc_id INT, bank TEXT, year INT, doc_type TEXT, lang TEXT, title TEXT, n_pages INT)
banks: bcge, bcv (French reports), efg, juliusbaer, swissquote, vontobel; years: 2024, 2025
(fiscal year, values at 31 December). One row per (bank, year, metric); a missing row means the
report does not give that metric."""

EXAMPLES = [
    ("Top 3 banks by CET1 ratio in 2025",
     "SELECT bank, value, doc_id, page_no FROM figures WHERE metric = 'cet1_ratio' "
     "AND year = 2025 ORDER BY value DESC LIMIT 3"),
    ("Julius Baer net profit in 2024 and 2025",
     "SELECT year, value, unit, doc_id, page_no FROM figures WHERE bank = 'juliusbaer' "
     "AND metric = 'net_profit' ORDER BY year"),
    ("Average cost/income ratio of the French-language banks in 2025",
     "SELECT round(avg(f.value), 1) AS avg_cir, array_agg(f.page_no) AS pages FROM figures f "
     "JOIN documents d ON d.doc_id = f.doc_id WHERE d.lang = 'fr' "
     "AND f.metric = 'cost_income_ratio' AND f.year = 2025"),
    ("Which banks grew total assets from 2024 to 2025?",
     "SELECT a.bank, a.value AS v2024, b.value AS v2025, b.doc_id, b.page_no FROM figures a "
     "JOIN figures b ON a.bank = b.bank AND a.metric = b.metric WHERE a.metric = 'total_assets' "
     "AND a.year = 2024 AND b.year = 2025 AND b.value > a.value"),
    ("Headcount of every bank in 2025, largest first",
     "SELECT bank, value, doc_id, page_no FROM figures WHERE metric = 'headcount_fte' "
     "AND year = 2025 ORDER BY value DESC"),
]  # fmt: skip


def tool_description(metrics: dict[str, dict]) -> str:
    vocab = "\n".join(
        f"- {k} ({m['unit']}): {m['definition']}"
        + (f" CAVEAT: {' '.join(m['caveat'].split())}" if m.get("caveat") else "")
        for k, m in metrics.items()
    )
    ex = "\n".join(f"Q: {q}\nSQL: {s}" for q, s in EXAMPLES)
    return (
        "Run ONE read-only PostgreSQL SELECT over key figures extracted from Swiss bank annual "
        f"reports (at most {MAX_ROWS} rows).\nTables:\n{SCHEMA}\nMetrics:\n{vocab}\n"
        "Always select doc_id and page_no so every figure can be cited. Units: CHF_m = CHF "
        "million, CHF_bn = CHF billion, pct = percent.\nExamples:\n" + ex
    )
