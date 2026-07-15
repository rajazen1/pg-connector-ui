"""PostgreSQL access with read-only enforcement.

Two layers of protection so this tool can never mutate the target database:
  1. A lightweight SQL guard rejects anything that isn't a read statement.
  2. The database session itself is forced read-only, so even if a write
     slipped past the guard, PostgreSQL rejects it.
"""
import re
import time
from threading import Lock

import psycopg2
from psycopg2 import pool as pg_pool

from . import runtime
from .config import settings

_pool: pg_pool.ThreadedConnectionPool | None = None
_pool_lock = Lock()

# Leading keyword must be one of these for a statement to be considered read-only.
_READ_ONLY_PREFIX = re.compile(
    r"^\s*(with|select|show|explain|table|values)\b", re.IGNORECASE
)
# Block obvious data/schema changing keywords appearing as standalone words.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"copy|vacuum|reindex|call|do|merge|comment|lock|refresh)\b",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


class QueryError(Exception):
    """Raised for validation / execution problems we want to surface to the UI."""


def _get_pool() -> pg_pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pg_pool.ThreadedConnectionPool(
                    minconn=1, maxconn=5, **runtime.db_dsn_kwargs()
                )
    return _pool


def reset_pool() -> None:
    """Drop the pool so the next query reconnects with the current DB config."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None


def test_connection(dsn_kwargs: dict) -> dict:
    """Try a one-off connection (not via the pool) and report ok / error."""
    try:
        conn = psycopg2.connect(**dsn_kwargs)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT version(), current_database()")
                version, database = cur.fetchone()
            return {"ok": True, "database": database, "version": version}
        finally:
            conn.close()
    except Exception as exc:
        return {"ok": False, "error": str(exc).strip()}


def _strip(sql: str) -> str:
    return _COMMENT.sub(" ", sql).strip().rstrip(";").strip()


def validate_read_only(sql: str) -> str:
    """Return the cleaned SQL if it is a single read-only statement, else raise."""
    cleaned = _strip(sql)
    if not cleaned:
        raise QueryError("Empty query.")
    if ";" in cleaned:
        raise QueryError("Only a single statement is allowed (no ';').")
    if not _READ_ONLY_PREFIX.match(cleaned):
        raise QueryError(
            "Only read queries are allowed "
            "(SELECT / WITH / SHOW / EXPLAIN / TABLE / VALUES)."
        )
    if _FORBIDDEN.search(cleaned):
        raise QueryError("Query contains a write/DDL keyword and was blocked.")
    return cleaned


def _run(sql: str, params=None, max_rows: int | None = None):
    """Execute one read-only statement (optionally parameterized) under a
    read-only session with a statement timeout. Returns (columns, rows, truncated).
    max_rows=None fetches everything the statement produces.
    """
    conn = None
    pool = None
    try:
        pool = _get_pool()          # may raise OperationalError if the DB is unreachable
        conn = pool.getconn()       # may raise PoolError if the pool is exhausted
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute(
                "SET statement_timeout = %s",
                (settings.QUERY_TIMEOUT_SECONDS * 1000,),
            )
            cur.execute(sql, params)
            if cur.description is None:
                return [], [], False
            columns = [d.name for d in cur.description]
            if max_rows is None:
                rows = cur.fetchall()
                truncated = False
            else:
                rows = cur.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                rows = rows[:max_rows]
            return columns, [_serialize_row(r) for r in rows], truncated
    except psycopg2.Error as exc:
        # Covers connect failures (OperationalError) and pool exhaustion
        # (PoolError) as well as query errors — all surface as a clean 400.
        raise QueryError(str(exc).strip()) from exc
    finally:
        if conn is not None and pool is not None:
            pool.putconn(conn)


def run_query(sql: str) -> dict:
    """Execute a validated read-only query and return columns + rows (capped)."""
    cleaned = validate_read_only(sql)
    started = time.perf_counter()
    columns, rows, truncated = _run(cleaned, None, settings.MAX_ROWS)
    return {
        "sql": cleaned,
        "columns": columns,
        "rows": rows,
        "rowCount": len(rows),
        "truncated": truncated,
        "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
    }


def run_paginated(
    base_sql: str,
    page: int = 0,
    page_size: int | None = None,
    sort_idx: int | None = None,
    sort_dir: str = "asc",
    filter_text: str = "",
) -> dict:
    """Page / sort / filter / count ANY read-only query inside PostgreSQL.

    The user's query is wrapped as a derived table so LIMIT/OFFSET, an ORDER BY
    (by column POSITION — injection-safe), a whole-row ILIKE filter (bound
    parameter), and count(*) all run in the database. Only one page is returned.
    """
    cleaned = validate_read_only(base_sql)
    page = max(0, int(page))
    page_size = min(max(1, int(page_size or settings.DEFAULT_PAGE_SIZE)), settings.MAX_ROWS)
    direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"

    # Double any '%' in the embedded query so psycopg2's param substitution
    # (which runs because we pass a params dict) treats them as literals.
    wrapped = cleaned.replace("%", "%%")

    params: dict = {"lim": page_size, "off": page * page_size}
    where = ""
    if filter_text:
        where = "WHERE _q::text ILIKE %(flt)s"
        params["flt"] = f"%{filter_text}%"
    order = f"ORDER BY {max(1, int(sort_idx))} {direction}" if sort_idx else ""

    data_sql = f"SELECT * FROM ({wrapped}) _q {where} {order} LIMIT %(lim)s OFFSET %(off)s"
    count_sql = f"SELECT count(*) FROM ({wrapped}) _q {where}"

    started = time.perf_counter()
    columns, rows, _ = _run(data_sql, params, None)
    _, crows, _ = _run(count_sql, ({"flt": params["flt"]} if filter_text else None), None)
    total = int(crows[0][0]) if crows else len(rows)

    return {
        "sql": cleaned,
        "columns": columns,
        "rows": rows,
        "rowCount": len(rows),
        "total": total,
        "page": page,
        "pageSize": page_size,
        "sortIdx": sort_idx,
        "sortDir": "desc" if direction == "DESC" else "asc",
        "filter": filter_text,
        "truncated": False,
        "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
    }


def _serialize_row(row) -> list:
    """Make every cell JSON-safe (dates, Decimals, bytes, etc.)."""
    out = []
    for v in row:
        if v is None or isinstance(v, (str, int, float, bool)):
            out.append(v)
        elif isinstance(v, (bytes, bytearray, memoryview)):
            out.append(f"\\x{bytes(v).hex()}")
        else:
            out.append(str(v))
    return out


def ping() -> bool:
    try:
        run_query("SELECT 1")
        return True
    except Exception:
        return False
