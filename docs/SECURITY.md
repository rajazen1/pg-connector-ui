# Security notes & TODO

Current security posture of PG Connector, and the one deferred item to address
before any external-facing deployment.

## What's already enforced ✅

### Read-only data access (two independent layers)
- **SQL guard** — only `SELECT / WITH / SHOW / EXPLAIN / TABLE / VALUES` statements
  are accepted; write/DDL keywords and multi-statements are rejected before running.
- **Read-only DB session** — every connection sets `default_transaction_read_only = on`,
  so even a write that slipped past the guard is rejected by PostgreSQL itself.
- A `statement_timeout` and a `MAX_ROWS` cap bound runaway/huge queries.
- Server-side pagination wraps queries as a derived table with **bound parameters**
  (filter) and **ordinal** sort — no SQL injection via filter/sort.

### Database credentials
- Connecting to a database requires **valid PostgreSQL credentials** — enforced by
  Postgres, not just the app. Wrong user/password/host → the connection is rejected
  and the UI surfaces the real error.

### Secret handling
- `GET /api/config` **never returns secrets** — only `passwordSet` / `apiKeySet`
  booleans. The DB password and LLM API key never leave the server.
- `backend/.env` and `backend/config.local.json` are **gitignored**; no secret has
  been committed.

## Deferred item ⚠️ — authenticate the Config tab

**Status: not implemented (deferred by decision, 2026-07-15).**

Today the app has **no login**. Anyone who can reach the URL can open the **Config**
tab and:
- repoint the app at a different database, or
- set/replace the LLM API key (a billing risk).

Existing secrets stay masked, but *who* may change configuration is not restricted.

### Recommended fix (when picked up)
An **admin password/token** gate — proportionate for a VNet-internal tool:
1. Add `ADMIN_TOKEN` (or `ADMIN_PASSWORD`) to `backend/.env`.
2. Protect the mutating config endpoints — `PUT /api/config/db`, `PUT /api/config/llm`
   (and optionally `GET /api/config`) — with a dependency that checks an
   `X-Admin-Token` header; return `401` if missing/wrong.
3. In the UI, the Config tab prompts for the token once and sends it on save.
4. Leave the Explorer (read-only queries) open, or gate it too if viewers must
   also authenticate (see the two-tier option).

### Deployment guidance (independent of the gate)
- Use **internal ingress** for the Container App (VNet-only), reachable via
  VPN/bastion/private endpoint — **not** a public URL.
- Connect to the database with a **read-only Postgres role** (`GRANT SELECT` only)
  as defense-in-depth, so the tool cannot write even if misconfigured.
- Keep `ADMIN_TOKEN` / DB password / LLM key as **Container App secrets**, never
  plaintext env vars (the deploy script already does this for DB/LLM).

## Related
- Deploy scripts: `deploy/deploy.ps1` / `deploy/deploy.sh` (secrets handled).
- Config store: `backend/app/runtime.py` (env fallback + `config.local.json` overrides).
