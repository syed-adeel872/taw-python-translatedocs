"""Application settings loaded from environment variables and .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration.

    PostgreSQL is the intended application database. A developer may point
    ``DATABASE_URL`` at SQLite for a local smoke run, but the documented and
    default configuration uses PostgreSQL.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "TranslateDocs"
    app_env: str = "development"
    app_debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000

    database_url: str = (
        "postgresql+psycopg://translatedocs:translatedocs@localhost:5432/translatedocs"
    )
    database_echo: bool = False

    storage_root: Path = Path("instance")
    max_upload_mb: int = Field(default=10, ge=1, le=100)

    ai_provider: str = "mock"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    openai_compat_api_key: str = ""
    openai_compat_base_url: str = ""
    openai_compat_model: str = ""

    ai_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    ai_max_retries: int = Field(default=3, ge=0, le=5)
    ai_batch_size: int = Field(default=20, ge=1, le=100)
    max_document_chars: int = Field(default=400_000, ge=1_000)
    pdf_font_path: str = ""

    @field_validator("ai_provider")
    @classmethod
    def _normalise_provider(cls, value: str) -> str:
        return value.strip().lower() or "mock"

    @property
    def storage_path(self) -> Path:
        path = self.storage_root
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @property
    def upload_dir(self) -> Path:
        return self.storage_path / "uploads"

    @property
    def output_dir(self) -> Path:
        return self.storage_path / "outputs"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
