"""FastAPI app: read-only PostgreSQL Q&A API + optional static frontend."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, llm, questions
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


@app.get("/api/health")
def health():
    return {
        "ok": db.ping(),
        "database": settings.PGDATABASE,
        "host": settings.PGHOST,
        "aiEnabled": settings.ai_ready,
        "aiProvider": settings.LLM_PROVIDER if settings.ai_ready else None,
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
        return db.run_query(sql)
    except db.QueryError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc), "sql": sql})


@app.post("/api/ai")
def ai(body: AskBody):
    if not settings.ai_ready:
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
        return db.run_query(sql)
    except db.QueryError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc), "sql": sql})


@app.post("/api/query")
def query(body: QueryBody):
    try:
        return db.run_query(body.sql)
    except db.QueryError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


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
