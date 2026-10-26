from app.clients.rag_mcp_client import RetrievalEvidence
from app.graph.state import RuleHit, initial_state
from app.llm.judge import JudgedFinding, Judgment, build_catalog, resolve
from app.schemas.review import ReviewRequest

TEXT = "5월 18일 탱크데이, 안 사면 평생 후회"
HIT = RuleHit(expression="안 사면 평생 후회", category="fear_and_anxiety", severity="medium")


def state_with_hit():
    state = initial_state(ReviewRequest(text=TEXT, context={"channel": "sns"}))
    state["rule_hits"] = [HIT]
    state["social_context_evidence"] = [
        RetrievalEvidence(document="기준", section="역사", snippet="사건 소비 금지")
    ]
    return state


def judged(quote: str) -> JudgedFinding:
    return JudgedFinding(
        category="historical_context",
        severity="high",
        quote=quote,
        reason="연상 가능",
        evidence_ids=["S1"],
    )


def resolve_with(risk: str, *quotes: str) -> dict:
    state = state_with_hit()
    judgment = Judgment(
        risk=risk,
        evidence_sufficient=True,
        summary="요약",
        findings=[judged(q) for q in quotes],
    )
    return resolve(judgment, state, build_catalog(state))


def test_banned_expression_the_model_skipped_is_still_listed() -> None:
    result = resolve_with("yes", "탱크데이")
    banned = [f for f in result["findings"] if f.quote == "안 사면 평생 후회"]
    assert [f.quote for f in banned] == ["안 사면 평생 후회"]
    assert banned[0].needs_human_review and banned[0].severity == "medium"
    semantic = [f for f in result["findings"] if f.detection_type == "SEMANTIC"]
    assert [f.quote for f in semantic] == ["탱크데이", "안 사면 평생 후회"]


def test_banned_expression_the_model_already_flagged_is_not_duplicated() -> None:
    result = resolve_with("yes", "탱크데이", "안 사면 평생 후회")
    quotes = [f.quote for f in result["findings"]]
    assert quotes.count("안 사면 평생 후회") == 1
    assert {f.detection_type for f in result["findings"] if f.quote == "안 사면 평생 후회"} == {
        "SEMANTIC"
    }


def test_no_risk_never_adds_findings() -> None:
    # A banned hit with "no risk" is held for a person elsewhere; it never becomes a finding here.
    assert resolve_with("no")["findings"] == []
