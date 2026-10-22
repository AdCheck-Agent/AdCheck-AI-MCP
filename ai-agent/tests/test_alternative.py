import json

import app.graph.graph as graph_module
import pytest
from app.graph.nodes.generate_alternative import generate_alternative
from app.graph.state import ReviewState, RuleHit, initial_state
from app.llm.client import set_review_model
from app.schemas.review import Evidence, Finding, ReviewRequest, ReviewResponse

TEXT = "5월 18일 기념 탱크데이 특별 할인, 안 사면 평생 후회"


class FakeModel:
    def __init__(self, *responses: str | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def alt(*items: tuple[int, str]) -> str:
    return json.dumps(
        {"suggestions": [{"index": i, "suggestion": s} for i, s in items]}, ensure_ascii=False
    )


def finding() -> Finding:
    return Finding(
        category="historical_context",
        severity="high",
        quote="탱크데이",
        reason="날짜와 결합해 역사적 사건을 연상시킬 수 있습니다.",
        evidence=[Evidence(document="기준 v1", section="역사", snippet="사건 소비 금지")],
        needs_human_review=False,
    )


def make_state() -> ReviewState:
    state = initial_state(ReviewRequest(text=TEXT, context={"channel": "sns"}))
    state["findings"] = [finding()]
    state["summary"] = "수정이 필요합니다."
    state["rule_hits"] = [
        RuleHit(expression="안 사면 평생 후회", category="fear_and_anxiety", severity="medium")
    ]
    return state


def test_without_model_keeps_mock_revise() -> None:
    result = generate_alternative(make_state())
    assert result["status"] == "revise"
    assert "findings" not in result


def test_suggestion_is_attached_to_each_finding() -> None:
    model = FakeModel(alt((0, "봄맞이 감사 할인")))
    set_review_model(model)
    result = generate_alternative(make_state())
    assert result["status"] == "revise"
    assert result["findings"][0].suggestion == "봄맞이 감사 할인"
    assert result["summary"] == "수정이 필요합니다."
    assert "탱크데이" in model.calls[0][1]


@pytest.mark.parametrize(
    "raw",
    [
        alt((0, "탱크데이 특별전")),  # reuses the original quote
        alt((0, "지금 놓치면 안 사면 평생 후회")),  # reuses a banned expression
        alt((1, "엉뚱한 index")),  # no answer for finding 0
        alt((0, "   ")) if False else json.dumps({"suggestions": [{"index": 0, "suggestion": ""}]}),
    ],
)
def test_untrustworthy_suggestion_falls_back_to_needs_review(raw: str) -> None:
    set_review_model(FakeModel(raw, raw))
    result = generate_alternative(make_state())
    assert result["status"] == "needs_review"
    assert result["findings"][0].needs_human_review is True
    assert result["findings"][0].suggestion is None


def test_malformed_output_is_retried_once() -> None:
    model = FakeModel("형식 오류", alt((0, "봄맞이 감사 할인")))
    set_review_model(model)
    assert generate_alternative(make_state())["status"] == "revise"
    assert len(model.calls) == 2


def test_model_failure_becomes_needs_review() -> None:
    model = FakeModel(TimeoutError("timeout"))
    set_review_model(model)
    assert generate_alternative(make_state())["status"] == "needs_review"
    assert len(model.calls) == 1


def test_graph_end_to_end_returns_suggestion(monkeypatch: pytest.MonkeyPatch) -> None:
    judged = {
        "risk": "yes",
        "evidence_sufficient": True,
        "summary": "이벤트명 수정이 필요합니다.",
        "findings": [
            {
                "category": "historical_context",
                "severity": "high",
                "quote": "탱크데이",
                "reason": "역사적 사건을 연상시킬 수 있습니다.",
                "evidence_ids": ["S1"],
            }
        ],
    }
    evidence = Evidence(document="기준 v1", section="역사", snippet="사건 소비 금지", rule_id="R1")
    monkeypatch.setattr(
        graph_module,
        "retrieve_social_context",
        lambda state: {"social_context_evidence": [evidence]},
    )
    set_review_model(
        FakeModel(json.dumps(judged, ensure_ascii=False), alt((0, "봄맞이 감사 할인")))
    )
    graph = graph_module.build_graph()
    result = graph.invoke(initial_state(ReviewRequest(text=TEXT, context={"channel": "sns"})))
    response = ReviewResponse.model_validate(result)
    assert response.status == "revise"
    assert response.findings[0].suggestion == "봄맞이 감사 할인"
