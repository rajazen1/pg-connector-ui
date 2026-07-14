"""Application configuration, read from environment (.env supported)."""
import os

from dotenv import load_dotenv

# Load a .env file sitting next to the backend/ folder if present.
load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    # --- PostgreSQL connection ---
    PGHOST: str = os.environ.get("PGHOST", "localhost")
    PGPORT: int = _int("PGPORT", 5432)
    PGUSER: str = os.environ.get("PGUSER", "postgres")
    PGPASSWORD: str = os.environ.get("PGPASSWORD", "postgres")
    PGDATABASE: str = os.environ.get("PGDATABASE", "appdb")
    # Azure Database for PostgreSQL requires SSL -> set PGSSLMODE=require
    PGSSLMODE: str = os.environ.get("PGSSLMODE", "prefer")

    # --- Query safety / limits ---
    MAX_ROWS: int = _int("MAX_ROWS", 1000)
    QUERY_TIMEOUT_SECONDS: int = _int("QUERY_TIMEOUT_SECONDS", 15)

    # --- CORS (comma separated origins for the Vite dev server) ---
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]

    # --- Optional: AI natural-language -> SQL ---
    # When enabled, a "AI (natural language)" tick box appears in the UI.
    LLM_ENABLED: bool = os.environ.get("LLM_ENABLED", "false").lower() in {
        "1", "true", "yes", "on"
    }
    # anthropic | openai | azure_openai | mock
    LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "azure_openai")
    LLM_MODEL: str = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "")
    # Azure OpenAI specifics
    AZURE_OPENAI_ENDPOINT: str = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_DEPLOYMENT: str = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
    AZURE_OPENAI_API_VERSION: str = os.environ.get(
        "AZURE_OPENAI_API_VERSION", "2024-06-01"
    )

    @property
    def ai_ready(self) -> bool:
        """AI is usable only if enabled AND (mock, or a key is configured)."""
        if not self.LLM_ENABLED:
            return False
        if self.LLM_PROVIDER == "mock":
            return True
        return bool(self.LLM_API_KEY)

    def dsn_kwargs(self) -> dict:
        return dict(
            host=self.PGHOST,
            port=self.PGPORT,
            user=self.PGUSER,
            password=self.PGPASSWORD,
            dbname=self.PGDATABASE,
            sslmode=self.PGSSLMODE,
            connect_timeout=10,
            application_name="pg-connector",
        )


settings = Settings()
