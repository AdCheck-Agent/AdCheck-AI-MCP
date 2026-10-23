from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    company_id: str | None = Field(default=None, min_length=1, max_length=100)
    # Files attached to this review; RAG returns every chunk of these documents.
    document_ids: (
        list[Annotated[str, Field(min_length=1, max_length=150, pattern=r"^[A-Za-z0-9_.:-]+$")]]
        | None
    ) = Field(default=None, min_length=1, max_length=100)


class ReviewRequest(InputModel):
    text: str = Field(min_length=1, max_length=2000)
    context: ReviewContext


class ReviewAccepted(BaseModel):
    status: Literal["accepted"] = "accepted"
    trace_id: str = Field(pattern=r"^trace_[0-9a-f]{32}$")


class Evidence(BaseModel):
    document: str = Field(min_length=1)
    section: str = Field(min_length=1)
    snippet: str = Field(min_length=1)
    rule_id: str | None = None
    version: str | None = None


class Finding(BaseModel):
    category: Category
    severity: Severity
    quote: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    suggestion: str | None = None
    needs_human_review: bool


class ReviewResponse(BaseModel):
    status: Status
    summary: str = Field(min_length=1)
    findings: list[Finding]
    related_criteria: list[str] = Field(default_factory=list)
    trace_id: str = Field(pattern=r"^trace_[0-9a-f]{32}$")
