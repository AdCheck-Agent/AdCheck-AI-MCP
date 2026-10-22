from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore"
    )

    tavily_api_key: SecretStr | None = None
    tavily_timeout_seconds: float = Field(default=5, gt=0, le=5)
    tavily_max_results: int = Field(default=3, ge=1, le=3)


@lru_cache
def get_settings() -> Settings:
    return Settings()
