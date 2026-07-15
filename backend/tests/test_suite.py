"""PG Connector — generic test suite for ALL functionalities.

Run it against the running stack (local Docker Postgres + backend):

    cd backend
    ./.venv/Scripts/python.exe tests/test_suite.py

What it covers:
  UNIT (no server/DB needed)
    - natural-language question -> SQL mapping (every intent)
    - read-only safety guard (allow / block matrix)
    - SQL fence cleaning + mock LLM
    - identifier quoting / injection rejection
    - provider request shapes (azure_openai, groq) via intercepted HTTP
  INTEGRATION (needs backend on TEST_BASE_URL, default http://127.0.0.1:8000)
    - every API endpoint
    - every rule-based user question, checked against the seeded demo data
    - write/DDL rejection at the guard AND at the DB (read-only session)
    - LLM natural-language path (only if the backend reports aiEnabled)

Exit code is non-zero if anything fails.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app import db, llm, questions  # noqa: E402
from app.config import settings  # noqa: E402

BASE = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")

_pass = 0
_fail = 0
_skip = 0


def ok(name, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}   {detail}")


def section(title):
    print(f"\n=== {title} ===")


# ─────────────────────────────────────────────────────────────────────────────
# 1. UNIT — question mapping
# ─────────────────────────────────────────────────────────────────────────────
def unit_question_mapping():
    section("UNIT · natural-language -> SQL mapping")
    cases = {
        "show tables": "information_schema.tables",
        "what tables exist": "information_schema.tables",
        "list databases": "pg_database",
        "show databases": "pg_database",
        "list schemas": "information_schema.schemata",
        "row counts": "pg_stat_user_tables",
        "rows per table": "pg_stat_user_tables",
        "database info": "current_database()",
        "what database am i connected to": "current_database()",
        "version": "version()",
        "columns in spans": "information_schema.columns",
        "describe projects": "information_schema.columns",
        "count spans": 'count(*) AS count FROM "spans"',
        "how many users": 'FROM "users"',
        "preview projects": 'FROM "projects" LIMIT 50',
        "sample spans": 'FROM "spans" LIMIT 50',
        "list projects": 'FROM "projects" LIMIT 50',
        "SELECT 1": "SELECT 1",
        "WITH x AS (SELECT 1) SELECT * FROM x": "WITH x AS",
    }
    for q, expect in cases.items():
        try:
            sql = questions.resolve(q)
            ok(f"resolve({q!r})", expect in sql, f"-> {sql!r}")
        except Exception as e:
            ok(f"resolve({q!r})", False, f"raised {e}")

    # Unknown -> ValueError (helpful hint)
    try:
        questions.resolve("what is the meaning of life")
        ok("unknown question -> error", False)
    except ValueError:
        ok("unknown question -> error", True)

    # NL question with ';' -> rejected
    try:
        questions.resolve("count users; drop table users")
        ok("';' in question -> rejected", False)
    except ValueError:
        ok("';' in question -> rejected", True)


# ─────────────────────────────────────────────────────────────────────────────
# 2. UNIT — read-only guard
# ─────────────────────────────────────────────────────────────────────────────
def unit_readonly_guard():
    section("UNIT · read-only guard")

    def blocked(sql):
        try:
            db.validate_read_only(sql)
            return False
        except db.QueryError:
            return True

    ok("SELECT allowed", not blocked("SELECT * FROM spans"))
    ok("WITH allowed", not blocked("WITH x AS (SELECT 1) SELECT * FROM x"))
    ok("SHOW allowed", not blocked("SHOW statement_timeout"))
    ok("EXPLAIN allowed", not blocked("EXPLAIN SELECT 1"))
    ok("trailing ';' allowed", not blocked("SELECT 1;"))
    ok("INSERT blocked", blocked("INSERT INTO spans VALUES (1)"))
    ok("UPDATE blocked", blocked("UPDATE spans SET name='x'"))
    ok("DELETE blocked", blocked("DELETE FROM spans"))
    ok("DROP blocked", blocked("DROP TABLE spans"))
    ok("TRUNCATE blocked", blocked("TRUNCATE spans"))
    ok("ALTER blocked", blocked("ALTER TABLE spans ADD c int"))
    ok("GRANT blocked", blocked("GRANT ALL ON spans TO x"))
    ok("multi-statement blocked", blocked("SELECT 1; SELECT 2"))
    ok("comment-hidden write blocked", blocked("SELECT 1 -- ok\n; DROP TABLE t"))
    ok("empty blocked", blocked("   "))


# ─────────────────────────────────────────────────────────────────────────────
# 3. UNIT — SQL cleaning, mock LLM, identifiers
# ─────────────────────────────────────────────────────────────────────────────
def unit_llm_and_idents():
    section("UNIT · SQL cleaning / mock LLM / identifiers")
    ok("fence strip ```sql", llm._clean_sql("```sql\nSELECT 1\n```") == "SELECT 1")
    ok("fence strip plain ```", llm._clean_sql("```\nSELECT 2\n```") == "SELECT 2")
    ok("trailing ';' stripped", llm._clean_sql("SELECT 3;") == "SELECT 3")
    ok("mock -> JOIN for 'most'", "JOIN" in llm._mock("which project has the most spans"))
    ok("mock -> rules fallback", "information_schema.tables" in llm._mock("show tables"))

    ok("quote_ident simple", questions.quote_ident("spans") == '"spans"')
    ok("quote_ident schema.table", questions.quote_ident("public.spans") == '"public"."spans"')
    for bad in ["spans; drop", "a b", "1abc", "a.b.c", "spans--"]:
        try:
            questions.quote_ident(bad)
            ok(f"quote_ident rejects {bad!r}", False)
        except ValueError:
            ok(f"quote_ident rejects {bad!r}", True)


# ─────────────────────────────────────────────────────────────────────────────
# 4. UNIT — provider request shapes (no real key; HTTP intercepted)
# ─────────────────────────────────────────────────────────────────────────────
def unit_provider_shapes():
    section("UNIT · LLM provider request shapes (intercepted)")
    from app import runtime as rt  # llm.py reads config from runtime.llm()
    real_post = llm.httpx.post
    real_llm = rt.llm
    captured = {}

    def set_cfg(**kw):
        base = {"enabled": True, "provider": "mock", "model": "", "apiKey": "FAKE",
                "azureEndpoint": "", "azureDeployment": "", "azureApiVersion": "2024-06-01"}
        base.update(kw)
        rt.llm = lambda: base

    class R:
        status_code = 200
        reason_phrase = "OK"
        text = ""

        def __init__(self, kind):
            self.kind = kind

        def json(self):
            if self.kind == "gemini":
                return {"candidates": [{"content": {"parts": [{"text": "SELECT 1"}]}}]}
            return {"choices": [{"message": {"content": "SELECT 1"}}]}

    try:
        # Azure OpenAI
        set_cfg(provider="azure_openai", apiKey="FAKE",
                azureEndpoint="https://res.openai.azure.com", azureDeployment="dep")
        llm.httpx.post = lambda url, headers=None, json=None, timeout=None: (
            captured.update(url=url, headers=headers, body=json) or R("openai"))
        llm.generate_sql("count spans", "schema")
        ok("azure URL", "/openai/deployments/dep/chat/completions" in captured["url"])
        ok("azure api-key header", captured["headers"].get("api-key") == "FAKE")
        ok("azure no model in body", "model" not in captured["body"])

        # Groq (OpenAI-compatible)
        set_cfg(provider="groq", model="llama-3.3-70b-versatile", apiKey="FAKE")
        llm.generate_sql("count spans", "schema")
        ok("groq URL", captured["url"] == "https://api.groq.com/openai/v1/chat/completions")
        ok("groq bearer auth", captured["headers"].get("Authorization", "").startswith("Bearer "))
        ok("groq model in body", captured["body"].get("model") == "llama-3.3-70b-versatile")

        # Gemini
        set_cfg(provider="gemini", model="gemini-2.5-flash", apiKey="FAKE")
        llm.httpx.post = lambda url, headers=None, json=None, timeout=None: (
            captured.update(url=url, headers=headers, body=json) or R("gemini"))
        llm.generate_sql("count spans", "schema")
        ok("gemini URL", "gemini-2.5-flash:generateContent" in captured["url"])
        ok("gemini systemInstruction", "systemInstruction" in captured["body"])

        # 401 surfaces body
        class Err:
            status_code = 401
            reason_phrase = "Unauthorized"
            text = '{"error":"bad key"}'

            def json(self):
                return {}

        set_cfg(provider="groq", apiKey="FAKE")
        llm.httpx.post = lambda url, headers=None, json=None, timeout=None: Err()
        try:
            llm.generate_sql("x", "y")
            ok("401 raises with body", False)
        except Exception as e:
            ok("401 raises with body", "bad key" in str(e))
    finally:
        llm.httpx.post = real_post
        rt.llm = real_llm


# ─────────────────────────────────────────────────────────────────────────────
# Integration helpers
# ─────────────────────────────────────────────────────────────────────────────
def _get(path, timeout=40):
    return httpx.get(BASE + path, timeout=timeout)


def _post(path, body, timeout=40):
    return httpx.post(BASE + path, json=body, timeout=timeout)


def integration():
    global _skip
    section("INTEGRATION · live API")
    try:
        h = _get("/api/health").json()
    except Exception as e:
        print(f"  SKIP  backend not reachable at {BASE} ({e})")
        _skip += 1
        return

    ok("health ok", h.get("ok") is True, str(h))

    # Endpoints
    tables = _get("/api/tables").json()
    names = {r[tables["columns"].index("table_name")] for r in tables["rows"]}
    ok("tables lists projects/spans/users", {"projects", "spans", "users"} <= names, str(names))

    cols = _get("/api/tables/spans/columns").json()
    ok("columns endpoint for spans", "column_name" in cols.get("columns", []), str(cols)[:120])

    # Every rule-based user question via /api/ask
    section("INTEGRATION · rule-based user questions (/api/ask)")
    asks = {
        "show tables": lambda r: r["rowCount"] >= 3,
        "list databases": lambda r: r["rowCount"] >= 1,
        "list schemas": lambda r: r["rowCount"] >= 1,
        "row counts": lambda r: any("spans" in map(str, row) for row in r["rows"]),
        "database info": lambda r: r["rowCount"] == 1,
        "columns in spans": lambda r: r["rowCount"] >= 5,
        "describe users": lambda r: r["rowCount"] >= 2,
        "count spans": lambda r: r["rows"][0][0] == 250,
        "count users": lambda r: r["rows"][0][0] == 3,
        "count projects": lambda r: r["rows"][0][0] == 3,
        "preview spans": lambda r: r["rowCount"] == 50,
        "list projects": lambda r: r["rowCount"] == 3,
    }
    for q, cond in asks.items():
        r = _post("/api/ask", {"question": q})
        try:
            ok(f"ask {q!r}", r.status_code == 200 and cond(r.json()), f"status={r.status_code}")
        except Exception as e:
            ok(f"ask {q!r}", False, f"{e} :: {r.text[:120]}")

    # Raw SQL + safety
    section("INTEGRATION · SQL + safety enforcement")
    r = _post("/api/query", {"sql": "SELECT status, count(*) FROM spans GROUP BY status ORDER BY 1"})
    ok("SQL SELECT works", r.status_code == 200 and r.json()["rowCount"] == 3, r.text[:120])

    for bad in ["DELETE FROM spans", "UPDATE spans SET name='x'", "DROP TABLE spans",
                "INSERT INTO users(email) VALUES('a')", "SELECT 1; SELECT 2"]:
        r = _post("/api/query", {"sql": bad})
        ok(f"blocked: {bad[:24]!r}", r.status_code == 400, f"status={r.status_code}")

    # DB-level read-only (passes the keyword guard, must be rejected by the session)
    r = _post("/api/query", {"sql": "SELECT nextval('projects_id_seq')"})
    body = r.json()
    ok("nextval blocked by read-only session",
       r.status_code == 400 and "read-only" in body.get("error", ""), str(body)[:120])

    # Config endpoints: DB + LLM test/override (overriding the .env fallback)
    section("INTEGRATION · Config endpoints (test / override)")
    cfg = _get("/api/config").json()
    ok("config masks secrets (no raw password/apiKey)",
       "password" not in cfg["db"] and "apiKey" not in cfg["llm"]
       and isinstance(cfg["db"].get("passwordSet"), bool)
       and isinstance(cfg["llm"].get("apiKeySet"), bool), str(cfg)[:120])

    r = _post("/api/config/test-db", {k: cfg["db"][k] for k in ("host", "port", "user", "database", "sslmode")})
    ok("test-db (saved creds) connects", r.json().get("ok") is True, r.text[:120])

    r = _post("/api/config/test-db", {"host": "nope.invalid.example", "port": 5432,
                                      "user": "x", "database": "x", "sslmode": "prefer"})
    jb = r.json()
    ok("test-db bad host fails gracefully (no hang)", jb.get("ok") is False and bool(jb.get("error")), str(jb)[:120])

    # test-llm: mock always works without a key and returns SQL
    r = _post("/api/config/test-llm", {"provider": "mock", "model": "", "apiKey": ""}, timeout=90)
    jb = r.json()
    ok("test-llm mock ok + returns SQL",
       jb.get("ok") is True and str(jb.get("sql", "")).lower().startswith(("select", "with")), str(jb)[:120])

    # test-llm: azure with no endpoint/deployment -> clear config error, no crash
    r = _post("/api/config/test-llm", {"provider": "azure_openai", "model": "gpt-4o-mini",
                                       "apiKey": "k", "azureEndpoint": "", "azureDeployment": ""})
    jb = r.json()
    ok("test-llm azure missing fields errors cleanly",
       jb.get("ok") is False and "endpoint" in jb.get("error", "").lower(), str(jb)[:120])

    # test-llm must NOT persist: saved provider unchanged after a mock test
    ok("test-llm does not mutate saved config",
       _get("/api/config").json()["llm"]["provider"] == cfg["llm"]["provider"], "provider changed!")

    # LLM path (only if enabled)
    section("INTEGRATION · LLM natural-language (/api/ai)")
    if not h.get("aiEnabled"):
        print("  SKIP  aiEnabled=false (set LLM_ENABLED + provider/key to test)")
        _skip += 1
        return
    print(f"  (provider: {h.get('aiProvider')} — first call may be slow on a cold connection)")
    ai_qs = [
        "how many spans are there",
        "which project has the most spans",
        "what is the average span duration per project",
        "how many users are admins",
        "show the 5 longest running spans",
    ]
    for q in ai_qs:
        try:
            r = _post("/api/ai", {"question": q}, timeout=90)
            j = r.json()
            good = (
                r.status_code == 200
                and isinstance(j.get("columns"), list)
                and j.get("sql", "").strip().lower().startswith(("select", "with"))
            )
            ok(f"ai {q!r}", good, f"status={r.status_code} sql={j.get('sql','')[:80]!r}")
        except httpx.TimeoutException:
            ok(f"ai {q!r}", False, "LLM call timed out (>90s)")
        except Exception as e:
            ok(f"ai {q!r}", False, str(e)[:140])


def main():
    unit_question_mapping()
    unit_readonly_guard()
    unit_llm_and_idents()
    unit_provider_shapes()
    integration()
    print(f"\n{'='*60}\nRESULT: {_pass} passed, {_fail} failed, {_skip} skipped")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
