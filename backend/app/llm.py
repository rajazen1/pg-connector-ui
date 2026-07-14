"""Optional LLM natural-language -> SQL translation.

Enabled via config (LLM_ENABLED + a provider/key). The model is given the
database schema and the question and must return a single read-only SELECT.
Whatever it returns still passes through db.validate_read_only before running,
so the read-only guarantee holds even if the model misbehaves.

Providers: anthropic | openai | azure_openai | mock
  - mock requires no API key and reuses the rule engine (+ a couple of demo
    JOIN/aggregate answers) so the AI wiring can be exercised offline.
"""
import re

import httpx

from . import questions
from .config import settings
from .db import run_query

SYSTEM_PROMPT = (
    "You are a PostgreSQL expert. Translate the user's question into ONE "
    "read-only SQL query for PostgreSQL. Rules:\n"
    "- Output ONLY the SQL. No prose, no markdown fences, no trailing semicolon.\n"
    "- Use only SELECT / WITH. Never INSERT/UPDATE/DELETE/DDL.\n"
    "- Use only tables and columns from the provided schema.\n"
    "- Add a sensible LIMIT (<= 200) when the result could be large.\n"
)

_FENCE = re.compile(r"^```(?:sql)?|```$", re.IGNORECASE | re.MULTILINE)


def build_schema_context() -> str:
    """A compact text description of user tables and their columns."""
    result = run_query(
        "SELECT table_schema, table_name, column_name, data_type "
        "FROM information_schema.columns "
        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
        "ORDER BY table_schema, table_name, ordinal_position"
    )
    tables: dict[str, list[str]] = {}
    for schema, table, col, dtype in result["rows"]:
        tables.setdefault(f"{schema}.{table}", []).append(f"{col} {dtype}")
    lines = ["Tables:"]
    for name, cols in tables.items():
        lines.append(f"- {name}({', '.join(cols)})")
    return "\n".join(lines)


def _clean_sql(text: str) -> str:
    text = _FENCE.sub("", text).strip()
    return text.rstrip(";").strip()


def generate_sql(question: str, schema_text: str) -> str:
    """Dispatch to the configured provider and return generated SQL."""
    provider = settings.LLM_PROVIDER
    user = f"{schema_text}\n\nQuestion: {question}\nSQL:"

    if provider == "mock":
        return _mock(question)
    if provider == "anthropic":
        return _clean_sql(_anthropic(user))
    if provider == "gemini":
        return _clean_sql(_gemini(user))
    if provider in ("openai", "azure_openai", "groq"):
        return _clean_sql(_openai_compatible(user, provider))
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")


# --- Providers ---------------------------------------------------------------

def _post(url: str, headers: dict, body: dict) -> dict:
    """POST + JSON, surfacing the provider's error body (401, bad deployment...)."""
    resp = httpx.post(url, headers=headers, json=body, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"{resp.status_code} {resp.reason_phrase}: {resp.text[:400]}")
    return resp.json()


def _anthropic(user: str) -> str:
    data = _post(
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": settings.LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        {
            "model": settings.LLM_MODEL,
            "max_tokens": 500,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user}],
        },
    )
    return data["content"][0]["text"]


def _openai_compatible(user: str, provider: str) -> str:
    """OpenAI chat-completions shape — shared by OpenAI, Azure OpenAI and Groq."""
    if provider == "azure_openai":
        if not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_DEPLOYMENT:
            raise RuntimeError(
                "Azure OpenAI needs AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT."
            )
        url = (
            f"{settings.AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/"
            f"{settings.AZURE_OPENAI_DEPLOYMENT}/chat/completions"
            f"?api-version={settings.AZURE_OPENAI_API_VERSION}"
        )
        headers = {"api-key": settings.LLM_API_KEY, "content-type": "application/json"}
        body = {}  # deployment identifies the model
    else:
        url = (
            "https://api.groq.com/openai/v1/chat/completions"
            if provider == "groq"
            else "https://api.openai.com/v1/chat/completions"
        )
        headers = {
            "Authorization": f"Bearer {settings.LLM_API_KEY}",
            "content-type": "application/json",
        }
        body = {"model": settings.LLM_MODEL}

    body.update(
        {
            "temperature": 0,
            "max_tokens": 500,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        }
    )
    data = _post(url, headers, body)
    return data["choices"][0]["message"]["content"]


def _gemini(user: str) -> str:
    """Google Gemini generateContent API."""
    model = settings.LLM_MODEL or "gemini-2.5-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={settings.LLM_API_KEY}"
    )
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 500},
    }
    data = _post(url, {"content-type": "application/json"}, body)
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _mock(question: str) -> str:
    """No-key demo: a couple of AI-style answers, else fall back to the rules."""
    low = question.lower()
    if re.search(r"\b(most|top|per project|by project|spans per project)\b", low):
        return (
            "SELECT p.name AS project, count(s.id) AS spans "
            "FROM projects p LEFT JOIN spans s ON s.project_id = p.id "
            "GROUP BY p.name ORDER BY spans DESC"
        )
    if "error" in low and "span" in low:
        return "SELECT status, count(*) AS n FROM spans GROUP BY status ORDER BY n DESC"
    return questions.resolve(question)
