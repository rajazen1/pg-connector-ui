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
                    minconn=1, maxconn=5, **settings.dsn_kwargs()
                )
    return _pool


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


def run_query(sql: str) -> dict:
    """Execute a validated read-only query and return columns + rows."""
    cleaned = validate_read_only(sql)
    pool = _get_pool()
    conn = pool.getconn()
    started = time.perf_counter()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # Force the whole session read-only and cap runtime.
            cur.execute("SET default_transaction_read_only = on")
            cur.execute(
                "SET statement_timeout = %s",
                (settings.QUERY_TIMEOUT_SECONDS * 1000,),
            )
            cur.execute(cleaned)
            if cur.description is None:
                return {
                    "sql": cleaned,
                    "columns": [],
                    "rows": [],
                    "rowCount": 0,
                    "truncated": False,
                    "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
                }
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(settings.MAX_ROWS + 1)
            truncated = len(rows) > settings.MAX_ROWS
            rows = rows[: settings.MAX_ROWS]
            return {
                "sql": cleaned,
                "columns": columns,
                "rows": [_serialize_row(r) for r in rows],
                "rowCount": len(rows),
                "truncated": truncated,
                "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
            }
    except psycopg2.Error as exc:
        # psycopg2 puts the useful bit in .pgerror / str(exc)
        raise QueryError(str(exc).strip()) from exc
    finally:
        pool.putconn(conn)


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
