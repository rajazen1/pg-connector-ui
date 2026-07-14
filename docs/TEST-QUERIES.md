# Test Queries & Questions — PG Connector

Every question, SQL query, and safety case exercised during verification, plus
the exact SQL each maps to. Run against the local Docker Postgres (`appdb`,
seeded with `projects`=3, `users`=3, `spans`=250).

---

## 1. Rule-based questions (`/api/ask`, Question mode — no AI)

| You type | SQL that runs | Result on seed data |
|---|---|---|
| `show tables` / `what tables exist` | `SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1,2` | projects, spans, users |
| `list databases` / `show databases` | `SELECT datname AS database FROM pg_database WHERE datistemplate = false ORDER BY datname` | appdb, postgres, … |
| `list schemas` | `SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog','information_schema') ORDER BY 1` | public |
| `row counts` / `rows per table` | `SELECT schemaname AS schema, relname AS table, n_live_tup AS estimated_rows FROM pg_stat_user_tables ORDER BY n_live_tup DESC` | spans 250, projects 3, users 3 |
| `database info` / `what database am i connected to` / `version` | `SELECT current_database() AS database, current_user AS "user", version() AS version, inet_server_addr()::text AS server_ip, inet_server_port() AS server_port` | appdb / postgres / PostgreSQL 16.14 … |
| `columns in spans` / `describe spans` / `schema of spans` | `SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name = 'spans' ORDER BY ordinal_position` | id, project_id, name, status, duration_ms, started_at |
| `describe users` | (same, table `users`) | id, email, role |
| `count spans` / `how many spans` | `SELECT count(*) AS count FROM "spans"` | 250 |
| `count users` | `SELECT count(*) AS count FROM "users"` | 3 |
| `count projects` | `SELECT count(*) AS count FROM "projects"` | 3 |
| `preview spans` / `sample spans` / `show me spans` | `SELECT * FROM "spans" LIMIT 50` | 50 rows |
| `preview projects` | `SELECT * FROM "projects" LIMIT 50` | 3 rows |
| `list projects` | `SELECT * FROM "projects" LIMIT 50` | 3 rows |

**Unknown question** → `what is the weather` / `what is the meaning of life` →
HTTP 400 with a helpful hint listing supported phrasings.

---

## 2. Raw SQL (`/api/query`, SQL mode) — passthrough, read-only

| SQL | Result |
|---|---|
| `SELECT 1` | 1 |
| `WITH x AS (SELECT 1) SELECT * FROM x` | 1 |
| `SELECT * FROM spans WHERE status = 'ERROR' LIMIT 3` | 3 error spans |
| `SELECT status, count(*) FROM spans GROUP BY status ORDER BY 1` | ERROR / OK / TIMEOUT counts |
| `SHOW statement_timeout` | 15s |
| `EXPLAIN SELECT 1` | query plan |

---

## 3. Safety cases — all correctly rejected

**Blocked by the keyword guard (HTTP 400):**
```sql
DELETE FROM spans
UPDATE spans SET name='x'
DROP TABLE spans
INSERT INTO users(email) VALUES('a')
INSERT INTO spans VALUES (1)
TRUNCATE spans
ALTER TABLE spans ADD c int
GRANT ALL ON spans TO x
SELECT 1; SELECT 2                 -- multiple statements
SELECT 1 -- ok\n; DROP TABLE t     -- comment-hidden second statement
                                   -- (empty / whitespace-only) also blocked
```

**Passes the keyword guard but blocked by the read-only DB session:**
```sql
SELECT nextval('projects_id_seq')  -- "cannot execute nextval() in a read-only transaction"
```
(Confirmed the sequence was NOT advanced.)

**Natural-language injection rejected:**
- `count users; drop table users` → rejected (`;` not allowed in a question)
- `quote_ident` rejects: `spans; drop`, `a b`, `1abc`, `a.b.c`, `spans--`

---

## 4. AI natural-language (`/api/ai`) — real Groq `llama-3.3-70b-versatile`

| You type | SQL the LLM generated | Result |
|---|---|---|
| `how many spans are there` | `SELECT COUNT(*) FROM public.spans LIMIT 200` | 250 |
| `which project has the most spans` | `SELECT p.name, COUNT(s.id) AS span_count FROM public.projects p JOIN public.spans s ON p.id = s.project_id GROUP BY p.name ORDER BY span_count DESC LIMIT 1` | temporal, 84 |
| `what is the average span duration per project` | `SELECT p.id, p.name, AVG(s.duration_ms) AS average_duration FROM public.projects p JOIN public.spans s ON p.id = s.project_id GROUP BY p.id, p.name ORDER BY average_duration DESC LIMIT 200` | phoenix ≈ 2372.8 ms … |
| `how many users are admins` | `SELECT COUNT(id) FROM public.users WHERE role = 'admin'` | 1 |
| `show the 5 longest running spans` | `SELECT id, project_id, name, status, duration_ms, started_at FROM public.spans ORDER BY duration_ms DESC LIMIT 5` | span-135 (4995 ms) … |

**Mock provider (keyless demo) sample:**
- `which project has the most spans` → canned JOIN/GROUP BY
- `show tables` → falls back to the rule engine

Every AI-generated query is still run through the read-only guard before execution.

---

## 5. API endpoints exercised
```
GET  /api/health                      -> {ok, database, host, aiEnabled, aiProvider}
GET  /api/meta                        -> current db / user / version
GET  /api/tables                      -> user tables
GET  /api/tables/{table}/columns      -> columns for a table
POST /api/ask     {question}          -> rule-based question -> SQL -> rows
POST /api/ai      {question}          -> LLM question -> SQL -> rows (when AI enabled)
POST /api/query   {sql}               -> raw read-only SQL -> rows
```

See [`backend/tests/test_suite.py`](../backend/tests/test_suite.py) to re-run all of the above (84 checks).
