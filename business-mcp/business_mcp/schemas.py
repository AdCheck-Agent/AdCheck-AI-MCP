from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

SearchStatus = Literal["ok", "empty", "timeout", "unavailable", "error"]


class SearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=400)


class RecentIssue(BaseModel):
    title: str
    url: HttpUrl
    snippet: str
    source: str
    score: float | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    content_check: Literal["not_checked"] = "not_checked"


class SearchResult(BaseModel):
    status: SearchStatus
    results: list[RecentIssue] = Field(default_factory=list)
    related_criteria: list[str] = Field(default_factory=list)
    mock: bool = False
    message: str


CheckpointLevel = Literal[
    "BANNED_WORD_CHECK",
    "SOCIAL_HISTORICAL_SEARCH",
    "COMPANY_VALUES_SEARCH",
    "EXTERNAL_SEARCH",
    "FINAL_ASSESSMENT",
    "ALTERNATIVE_GENERATION",
    "OUTPUT_VALIDATION",
    "COMPLETED",
]
CheckpointStatus = Literal["ok", "timeout", "unavailable", "error"]


class CheckpointResult(BaseModel):
    """Outcome of one PATCH /api/v1/reviews/checkpoint call to the backend."""

    status: CheckpointStatus
    http_status: int | None = None
    error_code: str | None = None
    trace_id: str | None = None
    retryable: bool = False
    message: str
