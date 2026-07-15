"""Runtime configuration: env values are the fallback, the UI can override them.

Overrides are persisted to config.local.json (gitignored, same trust level as
.env). Changing DB config rebuilds the connection pool; changing LLM config is
picked up on the next request — no restart needed.
"""
import json
import threading
from pathlib import Path

from .config import settings

_FILE = Path(__file__).resolve().parent.parent / "config.local.json"
_lock = threading.Lock()
_state: dict | None = None


def _defaults() -> dict:
    return {
        "db": {
            "host": settings.PGHOST,
            "port": settings.PGPORT,
            "user": settings.PGUSER,
            "password": settings.PGPASSWORD,
            "database": settings.PGDATABASE,
            "sslmode": settings.PGSSLMODE,
        },
        "llm": {
            "enabled": settings.LLM_ENABLED,
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL,
            "apiKey": settings.LLM_API_KEY,
            "azureEndpoint": settings.AZURE_OPENAI_ENDPOINT,
            "azureDeployment": settings.AZURE_OPENAI_DEPLOYMENT,
            "azureApiVersion": settings.AZURE_OPENAI_API_VERSION,
        },
    }


def _load() -> dict:
    global _state
    if _state is None:
        _state = _defaults()
        if _FILE.exists():
            try:
                saved = json.loads(_FILE.read_text(encoding="utf-8"))
                for section in ("db", "llm"):
                    if isinstance(saved.get(section), dict):
                        _state[section].update(saved[section])
            except Exception:
                pass  # corrupt file → fall back to env defaults
    return _state


def get() -> dict:
    return _load()


def db_cfg() -> dict:
    return _load()["db"]


def llm() -> dict:
    return _load()["llm"]


def update(section: str, values: dict) -> dict:
    """Merge non-None values into a section and persist."""
    with _lock:
        st = _load()
        clean = {k: v for k, v in values.items() if v is not None}
        st[section].update(clean)
        try:
            _FILE.write_text(json.dumps(st, indent=2), encoding="utf-8")
        except Exception:
            pass
        return st


def db_dsn_kwargs() -> dict:
    d = db_cfg()
    return dict(
        host=d["host"],
        port=int(d["port"]),
        user=d["user"],
        password=d["password"],
        dbname=d["database"],
        sslmode=d["sslmode"],
        connect_timeout=10,
        application_name="pg-connector",
    )


def ai_ready() -> bool:
    c = llm()
    if not c["enabled"]:
        return False
    if c["provider"] == "mock":
        return True
    return bool(c["apiKey"])
