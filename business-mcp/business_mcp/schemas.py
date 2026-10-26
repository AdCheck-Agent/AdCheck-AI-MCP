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
    """검수를 끝내지 못한 이유. FAILED CP에만 담는다."""

    model_config = ConfigDict(extra="forbid")
    code: Literal["REVIEW_TIMEOUT", "REVIEW_ERROR"]
    message: str = Field(min_length=1, max_length=500)
    # 실패할 때 실행 중이던 단계. 어떤 단계도 시작하기 전이면 None.
    stage: ReviewStage | None = None
    # 이번 검수의 Agent trace. BE가 COMPLETED 결과처럼 대조할 수 있게 한다.
    trace_id: str = Field(pattern=r"^trace_[0-9a-f]{32}$")


CheckpointStatus = Literal["ok", "timeout", "unavailable", "error"]


class CheckpointResult(BaseModel):
    """BE에 보낸 PATCH /api/v1/reviews/checkpoint 호출 한 번의 결과."""

    status: CheckpointStatus
    http_status: int | None = None
    error_code: str | None = None
    trace_id: str | None = None
    retryable: bool = False
    message: str
