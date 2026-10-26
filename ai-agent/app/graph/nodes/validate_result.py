import logging

from app.graph.nodes.rule_filter import normalize
from app.graph.state import ReviewState
from app.llm.evidence import to_evidence
from app.llm.judge import oversized_sources
from app.llm.spans import locate_findings
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
    """지적을 믿을 수 없는 이유를 돌려준다. 문제가 없으면 None."""
    if not finding.quote.strip() or normalize(finding.quote) not in source:
        return "원문에 없는 인용"
    if any(_key(e) not in retrieved for e in finding.evidence):
        return "검색 결과에 없는 근거"
    return None


def _missing_information(state: ReviewState) -> list[str]:
    """사람이 알아야 할 빈틈: 이번 검수에서 확인하지 못한 것."""
    missing: list[str] = []
    errors = state["rag_errors"]
    if "COMPANY_NOT_SPECIFIED" in errors:
        missing.append("기업 ID가 없어 기업 가치 기준은 검토하지 못했습니다.")
    if any(code.endswith("_FAILED") for code in errors):
        missing.append("근거 검색에 실패해 일부 기준을 확인하지 못했습니다.")
    for name in oversized_sources(state):
        missing.append(f"{name} 첨부 문서가 너무 커서 전부 불러오지 못했습니다.")
    external = state["external_search_result"]
    if state["external_search_attempted"] and external is not None and external.status != "ok":
        missing.append("외부 검색에 실패해 최신 사실을 확인하지 못했습니다.")
    return missing


def validate_result(state: ReviewState) -> dict:
    """응답이 Agent를 떠나기 전 마지막 관문.

    형식 오류는 예외를 낸다(버그이므로 오류로 드러낸다). 내용 문제는 확신 있는 답으로
    내보내지 않는다. 믿을 수 없는 지적은 버리고, 더 이상 뒷받침되지 않는 status는
    needs_review로 낮춘다.
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
            located = locate_findings(state["source_text"], [finding])
            if located:
                kept.extend(located)
            else:
                reasons.append("원문 위치가 일치하지 않는 지적")

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
    missing = _missing_information(state)
    if missing:
        update["missing_information"] = missing
    if state.get("related_criteria") and (not kept or status == "pass"):
        # 관련 기준은 지적을 설명하는 것이므로, 남은 지적이 없으면 설명할 것도 없다.
        update["related_criteria"] = []
    if kept != state["findings"]:
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
