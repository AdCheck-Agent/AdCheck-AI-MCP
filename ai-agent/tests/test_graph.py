import app.graph.graph as graph_module
import pytest
from app.graph.nodes.rule_filter import rule_filter
from app.graph.nodes.validate_result import validate_result
from app.graph.state import ReviewState, initial_state
from app.schemas.review import Evidence, Finding, ReviewRequest, ReviewResponse


def request() -> ReviewRequest:
    return ReviewRequest(text="정상적인 사람이 아닙니다", context={"channel": "sns"})


def test_compile_and_invoke_to_end() -> None:
    graph = graph_module.build_graph()
    assert "validate_result" in graph.get_graph().nodes
    result = graph.invoke(initial_state(request()))
    assert ReviewResponse.model_validate(result).status == "needs_review"
    assert result["rule_hits"]
    assert not result["evidence_sufficient"]


async def test_async_graph_reaches_end() -> None:
    graph = graph_module.build_graph()
    visited = []
    async for update in graph.astream(initial_state(request())):
        visited.extend(update)
    assert visited[-1] == "validate_result"


@pytest.mark.parametrize(
    ("sufficient", "risk", "expected"),
    [
        (False, "yes", "needs_review"),
        (True, "yes", "revise"),
        (True, "no", "pass"),
        (True, "uncertain", "needs_review"),
    ],
)
def test_full_graph_branches(
    monkeypatch: pytest.MonkeyPatch, sufficient: bool, risk: str, expected: str
) -> None:
    # 테스트 전용 검수기가 앞으로의 판정을 흉내 낸다. 실제 mock은 근거 충분을 지어내지 않는다.
    evidence = Evidence(document="기준 v1", section="역사", snippet="사건 소비 금지")
    found = Finding(
        category="historical_context",
        severity="high",
        quote="신상품",
        reason="테스트 전용",
        evidence=[evidence],
        suggestion="새 소식",
        needs_human_review=False,
    )

    def reviewer(state: ReviewState) -> dict[str, object]:
        return {
            "social_context_evidence": [evidence],
            "evidence_sufficient": sufficient,
            "risk": risk,
            "findings": [found] if risk == "yes" else [],
            "summary": "테스트 전용 판정",
        }

    monkeypatch.setattr(graph_module, "review_llm", reviewer)
    graph = graph_module.build_graph()
    clean = ReviewRequest(text="신상품을 소개합니다", context={"channel": "sns"})
    updates = list(graph.stream(initial_state(clean)))
    assert list(updates[-1]) == ["validate_result"]
    result = ReviewResponse.model_validate(graph.invoke(initial_state(clean)))
    assert result.status == expected


def test_rule_filter_does_not_decide_status() -> None:
    assert set(rule_filter(initial_state(request()))) == {"rule_hits"}


def test_validator_rejects_invalid_output() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        validate_result(initial_state(request()))
