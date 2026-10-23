from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    rag_database_url: str = "postgresql://adcheck:adcheck@localhost:5433/adcheck_rag"
    rag_embedding_model: str = "BAAI/bge-m3"
    rag_embedding_dim: int = Field(default=1024, ge=1)
    rag_model_cache: Path = ROOT / ".cache" / "embeddings"
    rag_max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1)
    rag_max_rows: int = Field(default=1000, ge=1, le=10000)
    rag_max_attached_chars: int = Field(default=30000, ge=1)
    rag_chunk_tokens: int = Field(default=512, ge=16, le=1024)
    rag_chunk_overlap: int = Field(default=64, ge=0, le=256)
    rag_statement_timeout_ms: int = Field(default=15000, ge=100)

    @model_validator(mode="after")
    def overlap_is_smaller_than_chunk(self) -> "Settings":
        if self.rag_chunk_overlap >= self.rag_chunk_tokens:
            raise ValueError("RAG_CHUNK_OVERLAP는 RAG_CHUNK_TOKENS보다 작아야 합니다.")
        return self

    @property
    def embedding_profile(self) -> str:
        return f"fastembed:{self.rag_embedding_model}:{self.rag_embedding_dim}"
