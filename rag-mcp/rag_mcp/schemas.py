from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

DocumentType = Literal["corporate_values", "sustainability_report", "ethics_policy"]


class SearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.0, ge=-1, le=1)


class CorporateQuery(SearchQuery):
    company_id: str = Field(min_length=1, max_length=100)
    include_synthetic: bool = False


class RetrievedEvidence(BaseModel):
    document: str
    section: str
    snippet: str
    rule_id: str
    version: str
    document_id: str
    chunk_id: str
    company_id: str | None = None
    document_type: str
    record_type: str
    source_urls: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    row_id: str | None = None
    synthetic: bool = False
    score: float
    published_at: date | None = None
    category: str | None = None
    verification_status: str | None = None


class SearchResult(BaseModel):
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    mock: bool = False
    status: Literal["ok", "empty"] = "empty"
    message: str = ""


class PolicyRow(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    row_id: str = Field(min_length=1, max_length=100)
    company_id: str = Field(min_length=1, max_length=100)
    document_id: str = Field(min_length=1, max_length=150)
    document_type: DocumentType
    title: str = Field(min_length=1, max_length=200)
    section: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)
    version: str = Field(min_length=1, max_length=50)
    source_url: HttpUrl | None = None
    published_at: date | None = None
    synthetic: bool

    @field_validator("synthetic", mode="before")
    @classmethod
    def synthetic_flag(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise ValueError("synthetic에는 true 또는 false를 입력하세요.")

    @field_validator("row_id", "company_id", "document_id")
    @classmethod
    def identifier(cls, value: str) -> str:
        if not all(c.isascii() and (c.isalnum() or c in "_-.:") for c in value):
            raise ValueError("ID에는 영문·숫자와 _ - . : 만 사용할 수 있습니다.")
        return value


class Chunk(BaseModel):
    chunk_id: str
    section: str
    content: str
    metadata: dict = Field(default_factory=dict)


class DocumentRecord(BaseModel):
    company_id: str | None
    document_id: str
    corpus: Literal["social", "corporate"]
    document_type: str
    title: str
    version: str
    synthetic: bool
    checksum: str
    chunks: list[Chunk]
    metadata: dict = Field(default_factory=dict)


class DocumentResult(BaseModel):
    company_id: str | None
    document_id: str
    document_type: str
    title: str
    version: str
    synthetic: bool
    revision: int
    chunk_count: int
    status: Literal["indexed"] = "indexed"
