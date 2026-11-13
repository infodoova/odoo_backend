"""
Guarded execution of LLM-written SQL.

The SQL agent lets a language model write a query that is then run against the data
warehouse. The model can be steered by the user's question or by text stored in the data
(product names, partner names), so the query is never trusted. Safety is therefore enforced
by the database and not by the prompt:

1. ``check_sql`` accepts one plain SELECT/WITH statement that only calls allow-listed
   functions and does not name any schema, catalog or system object.
2. ``run_scoped_query`` runs that statement in a read-only transaction with a statement
   timeout, on a connection whose ``search_path`` contains only temporary views. Each view
   is a copy of one allowed warehouse table (``fact_*`` / ``dim_*``) filtered to the caller's
   tenants (and companies). A table that is not one of those views simply does not exist for
   the query, so the model cannot read ``app_users``, ``tenants`` or another tenant's rows
   even if it ignores the tenant rule in its prompt.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Iterable, Optional

from sqlalchemy import text

# ── Policy ────────────────────────────────────────────────────────────────────

ALLOWED_TABLE_PREFIXES = ("fact_", "dim_")

MAX_SQL_LENGTH = 20_000
STATEMENT_TIMEOUT_MS = 15_000
LOCK_TIMEOUT_MS = 2_000
MAX_ROWS = 1_000

# Words that must never appear anywhere in the text (checked on the original text,
# comments and literals included, to stay at least as strict as the previous check).
BLOCKED_WORDS = (
    "insert", "update", "delete", "drop", "alter", "truncate", "create", "grant",
    "revoke", "merge", "copy", "replace", "vacuum", "analyze",
    "into",  # SELECT ... INTO creates a table
)

# Schemas and system objects a query may not name.
_FORBIDDEN_QUALIFIER = re.compile(
    r"\b(?:public|pg_catalog|information_schema|pg_temp\w*|pg_toast\w*)\s*\.", re.IGNORECASE
)
_FORBIDDEN_WORDS = re.compile(
    r"\b(?:pg_\w*|lo_\w*|dblink\w*|current_setting|set_config|"
    r"reg(?:class|proc|procedure|oper|operator|namespace|role|type|config|dictionary|collation)|"
    r"txid_\w*|xmlparse|query_to_xml\w*|table_to_xml\w*|cursor_to_xml|database_to_xml\w*|"
    r"schema_to_xml\w*)\b",
    re.IGNORECASE,
)

# Names that may be followed by "(" without being a function call.
_KEYWORDS_BEFORE_PAREN = {
    "in", "as", "on", "and", "or", "not", "from", "join", "where", "having", "select", "with",
    "over", "filter", "exists", "any", "all", "some", "values", "union", "intersect", "except",
    "case", "when", "then", "else", "end", "using", "by", "partition", "order", "group",
    "between", "like", "ilike", "similar", "is", "limit", "offset", "distinct", "lateral",
    "within", "array", "row", "rows", "range", "groups", "recursive", "materialized",
    "inner", "left", "right", "full", "outer", "cross", "natural", "to", "at", "for",
    "interval", "fetch", "first", "next", "only", "ties", "escape", "collate", "returning",
    "unbounded", "preceding", "following", "current", "tablesample", "ordinality", "key",
}

# Type names that look like calls: numeric(12,2), varchar(20), timestamp(0) ...
_TYPE_NAMES = {
    "numeric", "decimal", "varchar", "char", "character", "bpchar", "timestamp",
    "timestamptz", "time", "timetz", "bit", "varbit", "float", "real",
}

ALLOWED_FUNCTIONS = _TYPE_NAMES | {
    # aggregates
    "count", "sum", "avg", "min", "max", "stddev", "stddev_pop", "stddev_samp", "variance",
    "var_pop", "var_samp", "bool_and", "bool_or", "every", "array_agg", "string_agg",
    "percentile_cont", "percentile_disc", "mode", "corr", "covar_pop", "covar_samp",
    # window
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag", "lead",
    "first_value", "last_value", "nth_value",
    # math
    "abs", "ceil", "ceiling", "floor", "round", "trunc", "sign", "sqrt", "power", "exp", "ln",
    "log", "mod", "div", "greatest", "least",
    # strings
    "lower", "upper", "initcap", "length", "char_length", "character_length", "substr",
    "substring", "position", "trim", "ltrim", "rtrim", "btrim", "concat", "concat_ws", "left",
    "right", "split_part", "lpad", "rpad", "regexp_replace", "starts_with", "strpos", "reverse",
    "repeat", "translate", "overlay",
    # conversion / dates
    "cast", "to_char", "to_date", "to_number", "to_timestamp", "date_trunc", "date_part",
    "extract", "age", "now", "make_date", "make_interval", "date", "timezone", "isfinite",
    "justify_days", "justify_hours",
    # null handling, sets, arrays
    "coalesce", "nullif", "generate_series", "unnest", "array_length", "cardinality",
    "array_position", "array_to_string",
}

# A WITH-clause name ("WITH x AS (", ", y(a, b) AS (") is not a function call.
_CTE_NAME = re.compile(
    r"(?:\bwith\s+(?:recursive\s+)?|,\s*)([a-z_][a-z0-9_]*)\s*(?:\([^()]*\)\s*)?as\s*"
    r"(?:not\s+materialized\s+|materialized\s+)?\(",
)
_CALL = re.compile(r"\b([a-z_][a-z0-9_$]*)\s*\(")


class UnsafeSQLError(ValueError):
    """The statement is not allowed to run."""


# ── Lexing ────────────────────────────────────────────────────────────────────


def _lex(sql: str) -> tuple[str, str, Optional[str]]:
    """Return ``(clean, skeleton, error)``.

    ``clean`` is the statement without comments. ``skeleton`` is ``clean`` with string
    literals emptied and quoted identifiers replaced, so keyword checks cannot be fooled
    by text inside quotes.
    """
    clean: list[str] = []
    skel: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if ch == "-" and nxt == "-":  # line comment
            j = sql.find("\n", i)
            i = n if j == -1 else j
            clean.append(" ")
            skel.append(" ")
            continue

        if ch == "/" and nxt == "*":  # block comment (PostgreSQL allows nesting)
            depth, j = 1, i + 2
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif sql.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            if depth:
                return "", "", "unterminated comment"
            i = j
            clean.append(" ")
            skel.append(" ")
            continue

        if ch == "'":  # string literal
            prev = sql[i - 1] if i else ""
            if prev in ("e", "E", "&"):
                return "", "", "escape-style string literals are not allowed"
            j = i + 1
            while True:
                k = sql.find("'", j)
                if k == -1:
                    return "", "", "unterminated string literal"
                if k + 1 < n and sql[k + 1] == "'":
                    j = k + 2
                    continue
                break
            clean.append(sql[i:k + 1])
            skel.append("''")
            i = k + 1
            continue

        if ch == '"':  # quoted identifier
            j = i + 1
            while True:
                k = sql.find('"', j)
                if k == -1:
                    return "", "", "unterminated quoted identifier"
                if k + 1 < n and sql[k + 1] == '"':
                    j = k + 2
                    continue
                break
            ident = sql[i + 1:k].replace('""', '"')
            if re.match(r"\s*\(", sql[k + 1:]):
                return "", "", "quoted function names are not allowed"
            if _FORBIDDEN_WORDS.fullmatch(ident) or ident.lower() in {
                "public", "pg_catalog", "information_schema",
            }:
                return "", "", f"identifier '{ident}' is not allowed"
            clean.append(sql[i:k + 1])
            skel.append('"q"')
            i = k + 1
            continue

        if ch == "$":
            return "", "", "dollar quoting and parameters are not allowed"

        clean.append(ch)
        skel.append(ch)
        i += 1

    return "".join(clean), "".join(skel), None


# ── Validation ────────────────────────────────────────────────────────────────


def check_sql(sql: str) -> tuple[Optional[str], str]:
    """Validate a statement. Returns ``(reason, executable_sql)``.

    ``reason`` is ``None`` when the statement is acceptable, otherwise a short message that
    can be shown to the model. ``executable_sql`` is the statement without comments or a
    trailing semicolon.
    """
    if not sql or not sql.strip():
        return "empty statement", ""
    if len(sql) > MAX_SQL_LENGTH:
        return "statement is too long", ""

    lowered_original = sql.lower()
    for word in BLOCKED_WORDS:
        if re.search(rf"\b{word}\b", lowered_original):
            return f"'{word}' is not allowed (read-only queries only)", ""

    clean, skeleton, error = _lex(sql)
    if error:
        return error, ""

    skeleton = skeleton.strip().rstrip(";").strip()
    clean = clean.strip().rstrip(";").strip()
    low = skeleton.lower()

    if ";" in low:
        return "only one statement is allowed", ""
    if not low.startswith(("select", "with")):
        return "only SELECT statements are allowed", ""
    if re.search(r"\bfor\s+(?:no\s+key\s+)?(?:update|share)\b", low):
        return "row locking is not allowed", ""

    if _FORBIDDEN_QUALIFIER.search(low):
        return "schema-qualified names are not allowed; use the table name only", ""
    found = _FORBIDDEN_WORDS.search(low)
    if found:
        return f"'{found.group(0)}' is not allowed", ""

    cte_names = set(_CTE_NAME.findall(low))
    for name in _CALL.findall(low):
        if name in _KEYWORDS_BEFORE_PAREN or name in cte_names or name in ALLOWED_FUNCTIONS:
            continue
        return f"function '{name}' is not allowed", ""

    return None, clean


def is_safe_read_only(sql: str) -> bool:
    reason, _ = check_sql(sql)
    return reason is None


# ── Scoped execution ──────────────────────────────────────────────────────────

_TABLE_CACHE: dict[str, Any] = {"at": 0.0, "tables": {}}
_TABLE_CACHE_TTL = 300


def _allowed_tables(conn) -> dict[str, dict[str, str]]:
    """``{table: {column: data_type}}`` for the allowed warehouse tables (cached)."""
    now = time.time()
    if _TABLE_CACHE["tables"] and now - _TABLE_CACHE["at"] < _TABLE_CACHE_TTL:
        return _TABLE_CACHE["tables"]
    rows = conn.execute(text(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    )).fetchall()
    tables: dict[str, dict[str, str]] = {}
    for table, column, data_type in rows:
        if table.startswith(ALLOWED_TABLE_PREFIXES):
            tables.setdefault(table, {})[column] = data_type
    _TABLE_CACHE.update(at=now, tables=tables)
    return tables


def allowed_table_names() -> set[str]:
    """Names of the tables the SQL agent may query (used to build the schema prompt)."""
    from .db import engine
    with engine.connect() as conn:
        return set(_allowed_tables(conn))


def _scope_predicate(table: str, columns: dict[str, str], tenants: list[str], companies: list[int]) -> str:
    parts: list[str] = []
    if "tenant_id" in columns:
        cast = "::uuid" if columns["tenant_id"] == "uuid" else ""
        literals = ", ".join(f"'{t}'{cast}" for t in tenants)
        parts.append(f"tenant_id IN ({literals})")
    if companies:
        company_list = ", ".join(str(c) for c in companies)
        if table == "dim_companies":
            parts.append(f"id IN ({company_list})")
        elif "company_id" in columns:
            parts.append(f"company_id IN ({company_list})")
    return " AND ".join(parts)


def _validated_tenants(tenant_ids: Iterable[str]) -> list[str]:
    out = []
    for t in tenant_ids or []:
        try:
            out.append(str(uuid.UUID(str(t))))
        except (ValueError, AttributeError):
            continue
    return sorted(set(out))


def run_scoped_query(
    sql: str,
    tenant_ids: Iterable[str],
    company_ids: Optional[Iterable[int]] = None,
    *,
    max_rows: int = MAX_ROWS,
    timeout_ms: int = STATEMENT_TIMEOUT_MS,
) -> list[dict]:
    """Validate ``sql`` and run it read-only, restricted to the given tenants/companies.

    Raises ``UnsafeSQLError`` for a statement that fails validation or when there is no
    tenant scope, and the database error for any statement that fails to run.
    """
    reason, executable = check_sql(sql)
    if reason:
        raise UnsafeSQLError(reason)

    tenants = _validated_tenants(tenant_ids)
    if not tenants:
        raise UnsafeSQLError("no tenant scope: refusing to query without a tenant")
    companies = sorted({int(c) for c in (company_ids or [])})

    from .db import engine

    with engine.connect() as conn:
        try:
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            conn.exec_driver_sql(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MS}")
            for table, columns in _allowed_tables(conn).items():
                predicate = _scope_predicate(table, columns, tenants, companies)
                where = f" WHERE {predicate}" if predicate else ""
                conn.exec_driver_sql(
                    f'CREATE TEMP VIEW "{table}" AS SELECT * FROM public."{table}"{where}'
                )
            # From here on only the temporary views are visible, and nothing can be written.
            conn.exec_driver_sql("SET LOCAL search_path = pg_temp")
            conn.exec_driver_sql("SET LOCAL transaction_read_only = on")

            # Stream from a server-side cursor so a huge result is never loaded into memory.
            result = conn.execution_options(stream_results=True, max_row_buffer=max_rows).execute(
                text(executable)
            )
            columns = list(result.keys())
            fetched = result.fetchmany(max_rows)
            result.close()
            return [dict(zip(columns, row)) for row in fetched]
        finally:
            conn.rollback()  # drops the temporary views and any session settings
