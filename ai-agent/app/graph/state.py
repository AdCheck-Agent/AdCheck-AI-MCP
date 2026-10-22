from typing import Literal, NotRequired, TypedDict
from uuid import uuid4

from pydantic import BaseModel

from app.clients.business_mcp_client import RecentIssue, RecentIssueResult
from app.schemas.review import (
    Category,
    Evidence,
    Finding,
    ReviewContext,
    ReviewRequest,
    Severity,
    Status,
)


class RuleHit(BaseModel):
    expression: str
    category: Category
    severity: Severity
    enabled: bool = True


class ReviewState(TypedDict):
    source_text: str
    context: ReviewContext
    rule_hits: list[RuleHit]
    social_context_evidence: list[Evidence]
    corporate_value_evidence: list[Evidence]
    external_evidence: list[RecentIssue]
    external_search_query: str | None
    external_search_attempted: bool
    external_search_result: RecentIssueResult | None
    evidence_sufficient: bool
    risk: Literal["yes", "no", "uncertain"]
    status: NotRequired[Status]
    findings: list[Finding]
    summary: str
    trace_id: str


def initial_state(request: ReviewRequest) -> ReviewState:
    return ReviewState(
        source_text=request.text,
        context=request.context,
        rule_hits=[],
        social_context_evidence=[],
        corporate_value_evidence=[],
        external_evidence=[],
        external_search_query=None,
        external_search_attempted=False,
        external_search_result=None,
        evidence_sufficient=False,
        risk="uncertain",
        findings=[],
        summary="",
        trace_id=f"trace_{uuid4().hex}",
    )
