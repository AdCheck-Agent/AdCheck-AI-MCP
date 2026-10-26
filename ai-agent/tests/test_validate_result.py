import pytest
from app.graph.nodes.validate_result import validate_result
from app.graph.state import ReviewState, RuleHit, initial_state
from app.schemas.review import Evidence, Finding, ReviewRequest

TEXT = "5월 18일 기념 탱크데이 특별 할인"
EVIDENCE = Evidence(document="기준 v1", section="역사", snippet="사건 소비 금지")


def finding(quote: str = "탱크데이", suggestion: str | None = "봄맞이 할인", **kw) -> Finding:
    data = {
        "category": "historical_context",
        "severity": "high",
        "quote": quote,
        "reason": "역사적 사건 연상",
        "evidence": [EVIDENCE],
        "suggestion": suggestion,
        "needs_human_review": False,
    }
    return Finding(**{**data, **kw})


def make(status: str, findings: list[Finding], **kw) -> ReviewState:
    state = initial_state(ReviewRequest(text=TEXT, context={"channel": "sns"}))
    state["social_context_evidence"] = [EVIDENCE]
    state["evidence_sufficient"] = True
    state["status"] = status  # type: ignore[typeddict-item]
    state["findings"] = findings
    state["summary"] = "요약"
    state.update(kw)  # type: ignore[typeddict-item]
    return state


def test_valid_revise_gets_positions_without_changing_verdict() -> None:
    result = validate_result(make("revise", [finding()]))
    assert "status" not in result
    assert result["findings"][0].start_offset == TEXT.index("탱크데이")


def test_valid_pass_passes_untouched() -> None:
    assert validate_result(make("pass", [])) == {}


def test_revise_without_suggestion_is_downgraded() -> None:
    result = validate_result(make("revise", [finding(suggestion=None)]))
    assert result["status"] == "needs_review"
    assert result["findings"][0].needs_human_review is True
    assert "수정안" in result["summary"]


def test_suggestion_containing_quote_is_downgraded() -> None:
    result = validate_result(make("revise", [finding(suggestion="탱크데이 아님")]))
    assert result["status"] == "needs_review"


def test_quote_not_in_source_is_dropped_and_revise_downgraded() -> None:
    result = validate_result(make("revise", [finding(quote="없는 표현")]))
    assert result["status"] == "needs_review"
    assert result["findings"] == []


def test_one_bad_finding_dropped_other_kept() -> None:
    state = make("revise", [finding(), finding(quote="없는 표현")])
    result = validate_result(state)
    assert [f.quote for f in result["findings"]] == ["탱크데이"]
    assert "status" not in result


def test_evidence_not_retrieved_is_dropped() -> None:
    state = make("revise", [finding()], social_context_evidence=[])
    result = validate_result(state)
    assert result["status"] == "needs_review"
    assert result["findings"] == []


def test_pass_with_rule_hit_is_downgraded() -> None:
    hit = RuleHit(expression="특별", category="fear_and_anxiety", severity="low")
    result = validate_result(make("pass", [], rule_hits=[hit]))
    assert result["status"] == "needs_review"


def test_pass_with_insufficient_evidence_is_downgraded() -> None:
    result = validate_result(make("pass", [], evidence_sufficient=False))
    assert result["status"] == "needs_review"


def test_needs_review_stays_and_only_bad_findings_are_dropped() -> None:
    result = validate_result(make("needs_review", [finding(quote="없는 표현")]))
    assert result == {"findings": []}


def test_malformed_shape_still_raises() -> None:
    from pydantic import ValidationError

    state = make("revise", [finding()], summary=123)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        validate_result(state)
