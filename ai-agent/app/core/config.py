from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    ai_agent_port: int = Field(default=8000, ge=1, le=65535)
    rag_mcp_url: HttpUrl = HttpUrl("http://localhost:8001")
    rag_retrieval_enabled: bool = False
    business_mcp_url: HttpUrl = HttpUrl("http://localhost:8002")
    http_timeout_seconds: float = Field(default=10, gt=0)
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
