# PG Connector

A small web app to **ask questions about a PostgreSQL database** and see the
answers in a table. Plain-English questions ("show tables", "columns in orders",
"count users") are mapped to SQL; you can also drop into a raw **SQL** mode. All
access is **read-only** — the app refuses writes and forces a read-only DB session.

- **Backend:** FastAPI + psycopg2 (`backend/`)
- **Frontend:** React + Vite + TypeScript (`frontend/`)
- **Local DB:** seeded Postgres via docker-compose (`db/seed.sql`)

## Quick start (Windows / PowerShell)

**Prerequisites:** Docker Desktop (for the local DB), Python 3.12+, Node 18+.
The backend and frontend each keep running, so use **two separate terminals**.

### 1. Start a local database
```powershell
docker compose up -d          # Postgres on localhost:5432, database "appdb", seeded
```

### 2. Backend — terminal 1 (from project root)
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env    # defaults point at the local docker DB
uvicorn app.main:app --reload --port 8000   # http://127.0.0.1:8000
```

### 3. Frontend — terminal 2 (from project root)
```powershell
cd frontend
npm install
npm run dev                    # serves http://localhost:5173
```

Open **http://localhost:5173**. The Vite dev server proxies `/api` to the backend
on port 8000, so **both must be running**. (Prefer a single process? See
*Build one container* below — FastAPI can serve the built React app on one port.)

## Point it at your Azure PostgreSQL
Edit `backend/.env`:
```
PGHOST=zaf-phoenix-postgres.postgres.database.azure.com
PGUSER=zafadmin
PGPASSWORD=<secret>
PGDATABASE=postgres
PGSSLMODE=require
```
> The FQDN only resolves from **inside the VNet** (or wherever a private DNS
> zone / private endpoint makes it resolvable). From a laptop outside the VNet
> you'll get a connection/DNS error — run the container inside the VNet, or use
> the server's private IP, as discussed in the deployment plan.

## What you can ask
| Question | Runs |
|---|---|
| `show tables` | tables in user schemas |
| `list databases` | `pg_database` |
| `list schemas` | non-system schemas |
| `columns in <table>` / `describe <table>` | column list |
| `count <table>` / `how many <table>` | `count(*)` |
| `preview <table>` / `show me <table>` | `SELECT * ... LIMIT 50` |
| `row counts` | estimated rows per table |
| `database info` / `version` | current db / user / version |
| any `SELECT ...` (SQL mode) | passthrough (read-only) |

## Build one container (for Azure Container Apps)
```powershell
docker build -t pg-connector:latest .
docker run -p 8000:8000 --env-file backend/.env pg-connector:latest
# open http://localhost:8000  (FastAPI serves the built React app)
```

## Testing
`backend/tests/test_suite.py` is a self-contained suite covering **all**
functionality — no pytest needed:
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python tests/test_suite.py
```
It runs **unit** checks (question→SQL mapping, read-only guard, SQL cleaning,
identifier quoting, and each LLM provider's request shape via intercepted HTTP)
and, if the backend is up on `http://127.0.0.1:8000`, **integration** checks
(every endpoint, every rule-based question against the seeded data, write/DDL
rejection at the guard and at the DB, and the live LLM path when AI is enabled).
Point it elsewhere with `TEST_BASE_URL`. Exit code is non-zero on any failure.

## Safety
- Only `SELECT / WITH / SHOW / EXPLAIN / TABLE / VALUES` statements are allowed.
- Multiple statements and write/DDL keywords are rejected before execution.
- The DB session is set `default_transaction_read_only = on` and a
  `statement_timeout` is applied.
- Table names in generated queries are validated and quoted (no SQL injection).

## AI natural-language mode (optional)
By default questions are matched with **rules** (no API key needed). Enable the
**AI** tick box in the UI to have an LLM translate arbitrary English into SQL.
The generated SQL still passes through the same read-only guard before running.

Turn it on in `backend/.env`:
```
LLM_ENABLED=true
LLM_PROVIDER=azure_openai      # azure_openai | openai | groq | gemini | anthropic | mock
LLM_MODEL=gpt-4o-mini          # groq: llama-3.3-70b-versatile · gemini: gemini-2.5-flash
LLM_API_KEY=<key>
# Azure OpenAI also needs:
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
```
`LLM_PROVIDER=mock` needs no key — it's a demo that answers a couple of
JOIN/aggregate questions and otherwise falls back to the rules, so you can try
the tick box offline. When AI is enabled, `/api/health` reports `aiEnabled:true`
and the checkbox appears automatically.

## Deploy to Azure Container Apps
`deploy/deploy.ps1` (PowerShell) or `deploy/deploy.sh` builds the image in ACR
and creates/updates the `pg-connector` Container App in `zaf-aca-pvt-env` (the
private environment sharing the VNet with PostgreSQL), with external ingress.
The DB password and LLM key are stored as **Container App secrets**, never as
plaintext env vars. Edit the config block at the top (ACR name, etc.), then:
```powershell
$env:PGPASSWORD = "<db-password>"
./deploy/deploy.ps1
```

## UI
The interface follows the Zenlabs "Handler V2" design language (light neutrals +
indigo-violet accent, Inter / Plus Jakarta Sans, Tabler icons) to match the
hyperlink-engine app. The sidebar **Menu** switches between:
- **Explorer** — the query workspace (Question / SQL / AI).
- **Guide** — in-app help covering the three modes, example questions, 10 starter
  SQL queries, safety notes, and your schema. Every example is clickable and runs
  in the Explorer.
