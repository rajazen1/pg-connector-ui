"""Map plain-English database questions to safe SQL.

This is deliberately dependency-free pattern matching (no LLM). It covers the
common "explore my database" questions. Anything it doesn't recognise that
looks like SQL is passed straight through to the read-only executor; otherwise
we return a friendly hint listing what can be asked.
"""
import re

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str) -> str:
    """Validate and double-quote a possibly schema-qualified identifier."""
    parts = name.strip().split(".")
    if not (1 <= len(parts) <= 2):
        raise ValueError(f"Invalid identifier: {name!r}")
    safe = []
    for p in parts:
        p = p.strip().strip('"')
        if not _IDENT.match(p):
            raise ValueError(f"Invalid identifier part: {p!r}")
        safe.append('"' + p + '"')
    return ".".join(safe)


def _literal(name: str) -> str:
    """A validated identifier is also safe to embed as a string literal."""
    name = name.strip().strip('"')
    if not re.match(r"^[A-Za-z0-9_.]+$", name):
        raise ValueError(f"Invalid name: {name!r}")
    return "'" + name + "'"


def _last_table(text: str) -> str | None:
    """Pull a table name out of a question like 'columns in orders'."""
    m = re.search(
        r"\b(?:in|of|for|from|about|on)\s+(?:the\s+)?"
        r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)",
        text,
    )
    if m:
        return m.group(1)
    # fall back to the last word-ish token
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", text)
    return toks[-1] if toks else None


# Static answers keyed by intent.
_DATABASES = (
    "SELECT datname AS database FROM pg_database "
    "WHERE datistemplate = false ORDER BY datname"
)
_TABLES = (
    "SELECT table_schema, table_name FROM information_schema.tables "
    "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
    "ORDER BY table_schema, table_name"
)
_SCHEMAS = (
    "SELECT schema_name FROM information_schema.schemata "
    "WHERE schema_name NOT IN ('pg_catalog', 'information_schema') "
    "ORDER BY schema_name"
)
_ROWCOUNTS = (
    "SELECT schemaname AS schema, relname AS table, n_live_tup AS estimated_rows "
    "FROM pg_stat_user_tables ORDER BY n_live_tup DESC"
)
_DBINFO = (
    "SELECT current_database() AS database, current_user AS \"user\", "
    "version() AS version, inet_server_addr()::text AS server_ip, "
    "inet_server_port() AS server_port"
)


def resolve(question: str) -> str:
    """Return SQL for a natural-language question (or the question itself if SQL)."""
    q = question.strip()
    low = q.lower()

    # Already SQL? Let the executor validate/run it. 'show' is ambiguous:
    # "show tables/databases/schemas" is natural language, but anything else
    # ("show statement_timeout") is a genuine SQL SHOW command.
    if re.match(r"^\s*(with|select|explain|table|values)\b", low):
        return q
    m_show = re.match(r"^\s*show\s+(\w+)", low)
    if m_show and m_show.group(1) not in {
        "tables", "table", "databases", "database", "schemas", "schema"
    }:
        return q

    # A natural-language question must not smuggle in a second statement.
    if ";" in q:
        raise ValueError(
            "A question shouldn't contain ';'. Switch to SQL mode for statements."
        )

    if re.search(r"\b(databases|list db|show db)\b", low):
        return _DATABASES
    if re.search(r"\bschemas\b", low):
        return _SCHEMAS
    if re.search(r"\b(row ?counts?|rows per table|size of tables|biggest tables)\b", low):
        return _ROWCOUNTS
    if re.search(r"\b(db info|database info|connection info|what database|which database|version|current database)\b", low):
        return _DBINFO
    if re.search(r"\b(tables|relations)\b", low) and "columns" not in low:
        return _TABLES

    if re.search(r"\b(columns|describe|schema of|structure of|fields)\b", low):
        tbl = _last_table(low)
        if tbl:
            return (
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                f"WHERE table_name = {_literal(tbl.split('.')[-1])} "
                "ORDER BY ordinal_position"
            )

    if re.search(r"\b(count|how many|number of rows)\b", low):
        tbl = _last_table(low)
        if tbl:
            return f"SELECT count(*) AS count FROM {quote_ident(tbl)}"

    if re.search(r"\b(sample|preview|first rows|show me|top rows|peek|list)\b", low):
        tbl = _last_table(low)
        if tbl:
            return f"SELECT * FROM {quote_ident(tbl)} LIMIT 50"

    raise ValueError(
        "I couldn't map that to a query. Try: 'show tables', 'list databases', "
        "'columns in <table>', 'count <table>', 'preview <table>', "
        "'row counts', 'database info' — or type raw SQL (SELECT ...)."
    )
