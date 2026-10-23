import logging

from app.graph.nodes.rule_filter import normalize
from app.graph.state import ReviewState
from app.llm.evidence import to_evidence
from app.llm.judge import oversized_sources
from app.schemas.review import Evidence, Finding, ReviewResponse

logger = logging.getLogger(__name__)

DOWNGRADE_SUMMARY = "결과 검증을 통과하지 못해 사람 검토가 필요합니다. 사유: {reasons}"


def _key(evidence: Evidence) -> tuple[str, str, str]:
    return (evidence.document, evidence.section, evidence.snippet)


def _retrieved_keys(state: ReviewState) -> set[tuple[str, str, str]]:
    sources = (
        state["social_context_evidence"],
        state["corporate_value_evidence"],
        state["external_evidence"],
    )
    return {_key(to_evidence(e)) for evidences in sources for e in evidences}


def _check_finding(
    finding: Finding, source: str, retrieved: set[tuple[str, str, str]]
) -> str | None:
    """Return why a finding cannot be trusted, or None when it is fine."""
    if not finding.quote.strip() or normalize(finding.quote) not in source:
        return "원문에 없는 인용"
    if any(_key(e) not in retrieved for e in finding.evidence):
        return "검색 결과에 없는 근거"
    return None


def validate_result(state: ReviewState) -> dict:
    """Last gate before the response leaves the agent.

    Shape errors raise (a bug, surfaced as an error). Content problems never ship as a
    confident answer: untrustworthy findings are dropped, and a status that is no longer
    backed up is downgraded to needs_review.
    """
    ReviewResponse.model_validate(state)

    source = normalize(state["source_text"])
    retrieved = _retrieved_keys(state)
    reasons: list[str] = []

    kept: list[Finding] = []
    for finding in state["findings"]:
        reason = _check_finding(finding, source, retrieved)
        if reason:
            reasons.append(reason)
        else:
            kept.append(finding)

    status = state["status"]
    if status == "revise":
        if not kept:
            reasons.append("수정이 필요하다고 했지만 근거 있는 지적이 없음")
        elif any(not (f.suggestion or "").strip() for f in kept):
            reasons.append("수정안이 없는 지적")
        elif any(normalize(f.quote) in normalize(f.suggestion or "") for f in kept):
            reasons.append("수정안이 원래 표현을 포함")
    elif status == "pass":
        if kept:
            reasons.append("통과인데 지적이 남아 있음")
        if state["rule_hits"]:
            reasons.append("금기어가 탐지된 문구는 자동 통과 불가")
        if not state["evidence_sufficient"]:
            reasons.append("근거가 충분하지 않은데 통과 처리됨")
        if oversized_sources(state):
            reasons.append("첨부 문서를 전부 불러오지 못했는데 통과 처리됨")

    update: dict = {}
    if state.get("related_criteria") and (not kept or status == "pass"):
        # Criteria explain findings; with no finding left there is nothing to explain.
        update["related_criteria"] = []
    if len(kept) != len(state["findings"]):
        update["findings"] = kept

    blocking = [r for r in reasons if r != "원문에 없는 인용" and r != "검색 결과에 없는 근거"]
    if status != "needs_review" and (blocking or (status == "revise" and not kept)):
        logger.warning("validate_result downgraded status=%s reasons=%s", status, reasons)
        flagged = [f.model_copy(update={"needs_human_review": True}) for f in kept]
        update.update(
            status="needs_review",
            findings=flagged,
            summary=DOWNGRADE_SUMMARY.format(reasons=", ".join(dict.fromkeys(reasons))),
        )
    return update
