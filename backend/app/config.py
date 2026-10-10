"""Runtime configuration, read from environment variables (.env locally, Railway variables in prod)."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # backend/.env, wherever the server is started from
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parent.parent / ".env", extra="ignore")

    # Database. Railway injects DATABASE_URL as postgresql://...; we normalise it for psycopg 3.
    database_url: str = "postgresql+psycopg://atliq:atliq@localhost:5432/atliq"

    # LLM (Groq via LangChain). If no key is set the pipeline runs in a rule-based offline mode.
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    # Which provider reads captured conversations: "groq" (default) or "anthropic".
    # Email drafts and Ask AI always run on Groq.
    llm_provider: str = "groq"
    anthropic_api_key: str | None = None
    capture_claude_model: str = "claude-haiku-5-5"
    capture_claude_effort: str = "low"  # low | medium | high: thinking depth, and so cost
    llm_temperature: float = 0.0

    # Domain settings
    internal_domain: str = "atliq.com"
    sellers: str = "Bhavin,Dhaval,Karandeep,Jay"  # users who own deals
    inactive_days: int = 14  # FR-7 / dashboard flag
    proposal_unanswered_days: int = 7  # reminder trigger
    confidence_threshold: float = 0.7  # below this a draft is marked "needs review"

    # Optional fixed "today" so the synthetic dataset (dated July 2026) behaves realistically.
    reference_date: date | None = None

    # Background worker + scheduler
    worker_poll_seconds: int = 5
    reminder_scan_minutes: int = 30
    max_retries: int = 3

    # Kill switch (PRD rollout section): when false, nothing new is processed.
    processing_enabled: bool = True

    # Simple shared access code for the hosted demo. Empty = no login required.
    app_access_code: str = ""

    seed_on_startup: bool = True
    cors_origins: str = "http://localhost:5173"

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    @property
    def seller_list(self) -> list[str]:
        return [s.strip() for s in self.sellers.split(",") if s.strip()]

    @property
    def llm_enabled(self) -> bool:
        """Groq: email drafts and Ask AI always use it."""
        return bool(self.groq_api_key)

    @property
    def capture_provider(self) -> str:
        return "anthropic" if self.llm_provider.strip().lower() == "anthropic" else "groq"

    @property
    def capture_llm_enabled(self) -> bool:
        """The provider that reads captured conversations (classify, extract, dates, splits, cross-sell)."""
        return bool(self.anthropic_api_key) if self.capture_provider == "anthropic" else bool(self.groq_api_key)

    def today(self) -> date:
        return self.reference_date or date.today()


@lru_cache
def get_settings() -> Settings:
    return Settings()
