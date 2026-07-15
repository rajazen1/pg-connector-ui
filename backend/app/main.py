"""FastAPI app: read-only PostgreSQL Q&A API + optional static frontend."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, llm, probe, questions, runtime
from .config import settings

app = FastAPI(title="PG Connector", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskBody(BaseModel):
    question: str


class QueryBody(BaseModel):
    sql: str


class PageBody(BaseModel):
    sql: str
    page: int = 0
    pageSize: int | None = None
    sort: int | None = None      # 1-based column position, or null
    dir: str = "asc"
    filter: str = ""


class DbConfig(BaseModel):
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None
    database: str | None = None
    sslmode: str | None = None


class LlmConfig(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    model: str | None = None
    apiKey: str | None = None
    azureEndpoint: str | None = None
    azureDeployment: str | None = None
    azureApiVersion: str | None = None


@app.get("/api/health")
def health():
    d = runtime.db_cfg()
    return {
        "ok": db.ping(),
        "database": d["database"],
        "host": d["host"],
        "aiEnabled": runtime.ai_ready(),
        "aiProvider": runtime.llm()["provider"] if runtime.ai_ready() else None,
    }


@app.get("/api/meta")
def meta():
    try:
        return db.run_query(
            "SELECT current_database() AS database, current_user AS \"user\", "
            "version() AS version"
        )
    except db.QueryError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})


@app.get("/api/tables")
def tables():
    try:
        return db.run_query(questions._TABLES)
    except db.QueryError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})


@app.get("/api/tables/{table}/columns")
def columns(table: str):
    try:
        sql = questions.resolve(f"columns in {table}")
        return db.run_query(sql)
    except (ValueError, db.QueryError) as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/ask")
def ask(body: AskBody):
    try:
        sql = questions.resolve(body.question)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    try:
        return db.run_paginated(sql, 0)
    except db.QueryError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc), "sql": sql})


@app.post("/api/ai")
def ai(body: AskBody):
    if not runtime.ai_ready():
        return JSONResponse(
            status_code=400,
            content={"error": "AI mode is disabled. Set LLM_ENABLED=true and configure a provider."},
        )
    try:
        schema = llm.build_schema_context()
        sql = llm.generate_sql(body.question, schema)
    except Exception as exc:  # network/provider/validation issues
        return JSONResponse(status_code=502, content={"error": f"LLM error: {exc}"})
    try:
        return db.run_paginated(sql, 0)
    except db.QueryError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc), "sql": sql})


@app.post("/api/query")
def query(body: QueryBody):
    try:
        return db.run_paginated(body.sql, 0)
    except db.QueryError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/page")
def page(body: PageBody):
    """Fetch one page of an already-resolved query (sort/filter/count in SQL)."""
    try:
        return db.run_paginated(
            body.sql, body.page, body.pageSize, body.sort, body.dir, body.filter
        )
    except db.QueryError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc), "sql": body.sql})


@app.get("/api/vpn-status")
def vpn_status():
    """Live reachability of the configured database — the honest 'VPN' signal."""
    d = runtime.db_cfg()
    host, port = d["host"], int(d["port"])
    mode = probe.classify(host, settings.DEPLOY_MODE)
    if mode == "local-db":
        return {"mode": mode, "state": "n/a", "host": host, "latencyMs": None,
                "reason": "Local database — no VPN required."}
    return {"mode": mode, "host": host, **probe.probe_cached(host, port)}


# --- Runtime configuration (Config tab): DB + LLM, overriding the .env fallback ---
@app.get("/api/config")
def get_config():
    d = runtime.db_cfg()
    l = runtime.llm()
    return {
        "db": {
            "host": d["host"], "port": d["port"], "user": d["user"],
            "database": d["database"], "sslmode": d["sslmode"],
            "passwordSet": bool(d["password"]),
        },
        "llm": {
            "enabled": l["enabled"], "provider": l["provider"], "model": l["model"],
            "apiKeySet": bool(l["apiKey"]),
            "azureEndpoint": l["azureEndpoint"], "azureDeployment": l["azureDeployment"],
            "azureApiVersion": l["azureApiVersion"],
        },
    }


@app.put("/api/config/db")
def save_db_config(body: DbConfig):
    values = body.model_dump(exclude_none=True)
    if not values.get("password"):
        values.pop("password", None)  # blank => keep the existing password
    runtime.update("db", values)
    db.reset_pool()  # next query reconnects with the new settings
    return {"saved": True, **db.test_connection(runtime.db_dsn_kwargs())}


@app.put("/api/config/llm")
def save_llm_config(body: LlmConfig):
    values = body.model_dump(exclude_none=True)
    if values.get("apiKey") == "":
        values.pop("apiKey")  # blank => keep the existing key
    runtime.update("llm", values)
    return {"saved": True, "aiEnabled": runtime.ai_ready()}


@app.post("/api/config/test-db")
def test_db_config(body: DbConfig):
    base = runtime.db_cfg().copy()
    base.update(body.model_dump(exclude_none=True))
    if not base.get("password"):
        base["password"] = runtime.db_cfg()["password"]
    kwargs = dict(
        host=base["host"], port=int(base["port"]), user=base["user"],
        password=base["password"], dbname=base["database"], sslmode=base["sslmode"],
        connect_timeout=10, application_name="pg-connector-test",
    )
    return db.test_connection(kwargs)


@app.post("/api/config/test-llm")
def test_llm_config(body: LlmConfig):
    """Try the submitted LLM settings WITHOUT saving them: generate SQL for a
    trivial question and report success + the SQL, or the provider's error."""
    cfg = runtime.llm().copy()
    cfg.update(body.model_dump(exclude_none=True))
    if not cfg.get("apiKey"):
        cfg["apiKey"] = runtime.llm()["apiKey"]  # blank => keep the saved key
    if cfg.get("provider") != "mock" and not cfg.get("apiKey"):
        return {"ok": False, "error": "No API key set for this provider — enter one above."}
    try:
        schema = llm.build_schema_context()
        sql = llm.generate_sql("How many rows are in each table?", schema, cfg)
    except Exception as exc:  # network / auth / bad model or deployment
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "provider": cfg.get("provider"), "model": cfg.get("model"), "sql": sql}


# --- Serve the built React app if it has been bundled in (prod/Docker) ---
_STATIC = Path(__file__).resolve().parent / "static"
if _STATIC.is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = _STATIC / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC / "index.html")
