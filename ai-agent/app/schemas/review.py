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
    # When the ad will be posted; a date in the copy is judged against it.
    scheduled_at: AwareDatetime | None = None
    company_id: str | None = Field(default=None, min_length=1, max_length=100)
    # Files attached to this review; RAG returns every chunk of these documents.
    document_ids: (
        list[Annotated[str, Field(min_length=1, max_length=150, pattern=r"^[A-Za-z0-9_.:-]+$")]]
        | None
    ) = Field(default=None, min_length=1, max_length=100)


class ReviewRequest(InputModel):
    text: str = Field(min_length=1, max_length=2000)
    context: ReviewContext
    # Chosen by the backend; echoed on every stage event so it can tell reviews apart.
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
    # Where it was retrieved: social criteria, the company's own documents, or a web search.
    source: EvidenceSource | None = None


DetectionType = Literal["BANNED_WORD", "SEMANTIC"]


class Finding(BaseModel):
    # BANNED_WORD: the quote matches a banned expression; SEMANTIC: the model judged the meaning.
    detection_type: DetectionType = "SEMANTIC"
    category: Category
    severity: Severity
    quote: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    suggestion: str | None = None
    needs_human_review: bool
    # Words in the quote the judge named as the trigger; internal to the suggestion checks.
    trigger_terms: list[str] = Field(default_factory=list, exclude=True)


class ReviewResponse(BaseModel):
    status: Status
    summary: str = Field(min_length=1)
    findings: list[Finding]
    related_criteria: list[str] = Field(default_factory=list)
    # What could not be checked (no company, search failed, ...) so a person knows the gap.
    missing_information: list[str] = Field(default_factory=list)
    trace_id: str = Field(pattern=r"^trace_[0-9a-f]{32}$")
