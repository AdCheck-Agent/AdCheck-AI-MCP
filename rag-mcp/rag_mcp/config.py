from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    rag_database_url: str = "postgresql://adcheck:adcheck@localhost:5433/adcheck_rag"
    rag_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    rag_model_cache: Path = ROOT / ".cache" / "embeddings"
    rag_max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1)
    rag_max_rows: int = Field(default=1000, ge=1, le=10000)
    rag_max_attached_chars: int = Field(default=30000, ge=1)
    rag_chunk_tokens: int = Field(default=96, ge=16, le=110)
    rag_chunk_overlap: int = Field(default=12, ge=0, le=15)
    rag_statement_timeout_ms: int = Field(default=15000, ge=100)

    @property
    def embedding_profile(self) -> str:
        return f"fastembed:{self.rag_embedding_model}:384"
