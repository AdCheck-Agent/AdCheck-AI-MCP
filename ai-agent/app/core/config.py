from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    ai_agent_port: int = Field(default=8000, ge=1, le=65535)
    rag_mcp_url: HttpUrl = HttpUrl("http://localhost:8001")
    business_mcp_url: HttpUrl = HttpUrl("http://localhost:8002")
    qdrant_url: HttpUrl = HttpUrl("http://localhost:6333")
    http_timeout_seconds: float = Field(default=10, gt=0)
    review_timeout_seconds: float = Field(default=60, gt=0)
    log_level: str = "INFO"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
