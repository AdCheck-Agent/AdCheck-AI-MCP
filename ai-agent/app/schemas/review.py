from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Status = Literal["pass", "revise", "needs_review"]
Severity = Literal["low", "medium", "high"]
Category = Literal[
    "historical_context",
    "korea_japan_history",
    "social_issue",
    "fear_and_anxiety",
    "discrimination_and_hate",
    "labor_and_human_rights",
    "external_partner_risk",
    "corporate_value",
]


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class ReviewContext(InputModel):
    channel: Literal["sns"]
    campaign_name: str | None = Field(default=None, max_length=100)
    campaign_purpose: str | None = Field(default=None, max_length=200)
    # 광고 게시 예정일. 문구 속 날짜를 이 날짜와 비교해 판단한다.
    scheduled_at: AwareDatetime | None = None
    company_id: str | None = Field(default=None, min_length=1, max_length=100)
    # 이번 검수에 첨부한 파일. RAG가 이 문서들의 조각을 모두 돌려준다.
    document_ids: (
        list[Annotated[str, Field(min_length=1, max_length=150, pattern=r"^[A-Za-z0-9_.:-]+$")]]
        | None
    ) = Field(default=None, min_length=1, max_length=100)


class ReviewRequest(InputModel):
    text: str = Field(min_length=1, max_length=2000)
    context: ReviewContext
    # BE가 정한다. 모든 단계 이벤트에 그대로 실어 BE가 검수를 구분하게 한다.
    review_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    )


class ReviewAccepted(BaseModel):
    status: Literal["accepted"] = "accepted"
    trace_id: str = Field(pattern=r"^trace_[0-9a-f]{32}$")


EvidenceSource = Literal["social", "corporate", "external"]


class Evidence(BaseModel):
    document: str = Field(min_length=1)
    section: str = Field(min_length=1)
    snippet: str = Field(min_length=1)
    rule_id: str | None = None
    version: str | None = None
    # 근거를 가져온 곳: 사회 기준, 기업 자체 문서, 웹 검색.
    source: EvidenceSource | None = None


DetectionType = Literal["BANNED_WORD", "SEMANTIC"]


class Finding(BaseModel):
    # Agent의 지적은 의미 기반이다. 사전 기반 금기어 탐지는 BE가 맡는다.
    detection_type: DetectionType = "SEMANTIC"
    category: Category
    severity: Severity
    quote: str = Field(min_length=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    suggestion: str | None = None
    needs_human_review: bool
    # 판정이 문제 단어로 지목한 인용 속 단어. 수정안 검사에만 쓰는 내부 값이다.
    trigger_terms: list[str] = Field(default_factory=list, exclude=True)


class ReviewResponse(BaseModel):
    status: Status
    summary: str = Field(min_length=1)
    findings: list[Finding]
    related_criteria: list[str] = Field(default_factory=list)
    # 확인하지 못한 것(기업 없음, 검색 실패 등). 사람이 빈틈을 알 수 있게 한다.
    missing_information: list[str] = Field(default_factory=list)
    trace_id: str = Field(pattern=r"^trace_[0-9a-f]{32}$")
