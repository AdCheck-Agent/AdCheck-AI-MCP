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


ReviewStage = Literal[
    "BANNED_WORD_CHECK",
    "SOCIAL_HISTORICAL_SEARCH",
    "COMPANY_VALUES_SEARCH",
    "EXTERNAL_SEARCH",
    "FINAL_ASSESSMENT",
    "ALTERNATIVE_GENERATION",
    "OUTPUT_VALIDATION",
]
CheckpointLevel = Literal[ReviewStage, "COMPLETED", "FAILED"]


class CheckpointError(BaseModel):
    """Why the review could not finish; sent only with the FAILED CP."""

    model_config = ConfigDict(extra="forbid")
    code: Literal["REVIEW_TIMEOUT", "REVIEW_ERROR"]
    message: str = Field(min_length=1, max_length=500)
    # The stage that was running when it failed; None when no stage had started.
    stage: ReviewStage | None = None
    # The agent's trace for this review, so the backend can match it like a COMPLETED result.
    trace_id: str = Field(pattern=r"^trace_[0-9a-f]{32}$")


CheckpointStatus = Literal["ok", "timeout", "unavailable", "error"]


class CheckpointResult(BaseModel):
    """Outcome of one PATCH /api/v1/reviews/checkpoint call to the backend."""

    status: CheckpointStatus
    http_status: int | None = None
    error_code: str | None = None
    trace_id: str | None = None
    retryable: bool = False
    message: str
