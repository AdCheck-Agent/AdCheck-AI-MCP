import json

import app.graph.graph as graph_module
import pytest
from app.graph.nodes.review_llm import review_llm
from app.graph.state import ReviewState, RuleHit, initial_state
from app.llm.client import set_review_model
from app.schemas.review import Evidence, ReviewRequest, ReviewResponse

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


def judgment(**overrides: object) -> str:
    body: dict[str, object] = {
        "risk": "yes",
        "evidence_sufficient": True,
        "summary": "역사적 사건을 연상시키는 이벤트명이어서 수정이 필요합니다.",
        "findings": [
            {
                "category": "historical_context",
                "severity": "high",
                "quote": "탱크데이",
                "reason": "특정 날짜와 결합해 역사적 사건을 연상시킬 수 있습니다.",
                "evidence_ids": ["S1"],
                "needs_human_review": False,
            }
        ],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


def evidence() -> Evidence:
    return Evidence(
        document="사회적 맥락 검수 기준 v1",
        section="역사·기억 왜곡",
        snippet="역사적 사건을 이벤트명으로 소비하는 표현은 사람 검토가 필요하다.",
        rule_id="RULE-HIST-001",
        version="v1",
    )


def make_state(with_evidence: bool = True, with_hit: bool = True) -> ReviewState:
    state = initial_state(ReviewRequest(text=TEXT, context={"channel": "sns"}))
    if with_evidence:
        state["social_context_evidence"] = [evidence()]
    if with_hit:
        state["rule_hits"] = [
            RuleHit(expression="안 사면 평생 후회", category="fear_and_anxiety", severity="medium")
        ]
    return state


@pytest.fixture(autouse=True)
def reset_model():
    yield
    set_review_model(None)


def test_without_model_keeps_mock_behavior() -> None:
    result = review_llm(make_state())
    assert result["risk"] == "uncertain"
    assert not result["evidence_sufficient"]
    assert result["findings"] == []


def test_risk_with_valid_evidence_is_revise_ready() -> None:
    set_review_model(FakeModel(judgment()))
    result = review_llm(make_state())
    assert result["risk"] == "yes"
    assert result["evidence_sufficient"]
    finding = result["findings"][0]
    assert finding.evidence[0].rule_id == "RULE-HIST-001"
    assert finding.needs_human_review is False


def test_no_risk_with_evidence_is_pass_ready() -> None:
    set_review_model(FakeModel(judgment(risk="no", findings=[])))
    result = review_llm(make_state(with_hit=False))
    assert (result["risk"], result["evidence_sufficient"], result["findings"]) == ("no", True, [])


def test_rule_hit_with_no_risk_is_held_for_review() -> None:
    set_review_model(FakeModel(judgment(risk="no", findings=[])))
    result = review_llm(make_state(with_hit=True))
    assert result["risk"] == "uncertain"
    assert "안 사면 평생 후회" in result["summary"]
    assert result["findings"] == []


def test_prompt_carries_rule_hits_and_evidence_ids() -> None:
    model = FakeModel(judgment())
    set_review_model(model)
    review_llm(make_state())
    user = model.calls[0][1]
    assert "안 사면 평생 후회" in user
    assert '"id": "S1"' in user


def test_model_still_runs_when_rule_hits_are_absent() -> None:
    model = FakeModel(judgment(risk="no", findings=[]))
    set_review_model(model)
    review_llm(make_state(with_hit=False))
    assert len(model.calls) == 1


def test_no_evidence_forces_needs_review_even_if_model_says_safe() -> None:
    set_review_model(FakeModel(judgment(risk="no", findings=[])))
    result = review_llm(make_state(with_evidence=False))
    assert result["risk"] == "uncertain"
    assert not result["evidence_sufficient"]
    assert "안 사면 평생 후회" in result["summary"]


def test_quote_not_in_source_is_dropped_and_risk_downgraded() -> None:
    bad = {"quote": "원문에 없는 표현", "evidence_ids": ["S1"]}
    finding = json.loads(judgment())["findings"][0] | bad
    set_review_model(FakeModel(judgment(findings=[finding])))
    result = review_llm(make_state())
    assert result["findings"] == []
    assert result["risk"] == "uncertain"
    assert not result["evidence_sufficient"]


def test_unknown_evidence_id_cannot_support_a_risk() -> None:
    finding = json.loads(judgment())["findings"][0] | {"evidence_ids": ["S9"]}
    set_review_model(FakeModel(judgment(findings=[finding])))
    result = review_llm(make_state())
    assert result["risk"] == "uncertain"
    assert all(f.needs_human_review for f in result["findings"])


def test_uncertain_model_answer_is_kept() -> None:
    set_review_model(FakeModel(judgment(risk="uncertain", evidence_sufficient=False)))
    result = review_llm(make_state())
    assert result["risk"] == "uncertain"
    assert all(f.needs_human_review for f in result["findings"])


def test_fenced_json_is_parsed() -> None:
    set_review_model(FakeModel(f"```json\n{judgment()}\n```"))
    assert review_llm(make_state())["risk"] == "yes"


def test_malformed_output_is_retried_once() -> None:
    model = FakeModel("JSON이 아닙니다", judgment())
    set_review_model(model)
    assert review_llm(make_state())["risk"] == "yes"
    assert len(model.calls) == 2


def test_two_malformed_outputs_become_needs_review() -> None:
    model = FakeModel("나쁜 출력", '{"risk": "maybe"}')
    set_review_model(model)
    result = review_llm(make_state())
    assert result["risk"] == "uncertain"
    assert len(model.calls) == 2


def test_model_failure_becomes_needs_review_without_retry() -> None:
    model = FakeModel(TimeoutError("timeout"))
    set_review_model(model)
    result = review_llm(make_state())
    assert result["risk"] == "uncertain"
    assert len(model.calls) == 1


@pytest.mark.parametrize(
    ("raw", "text", "expected"),
    [
        (judgment(), TEXT, "revise"),
        (judgment(risk="no", findings=[]), "새로운 상품을 소개합니다", "pass"),
        (judgment(risk="no", findings=[]), TEXT, "needs_review"),
    ],
)
def test_graph_end_to_end_with_model_and_evidence(
    monkeypatch: pytest.MonkeyPatch, raw: str, text: str, expected: str
) -> None:
    monkeypatch.setattr(
        graph_module,
        "retrieve_social_context",
        lambda state: {"social_context_evidence": [evidence()]},
    )
    # TEXT also holds a banned expression, which gets a second finding and its own suggestion.
    alternative = (
        '{"suggestions": [{"index": 0, "suggestion": "봄맞이 감사 할인"},'
        ' {"index": 1, "suggestion": "지금 만나보세요"}]}'
    )
    set_review_model(FakeModel(raw, alternative))
    graph = graph_module.build_graph()
    result = graph.invoke(initial_state(ReviewRequest(text=text, context={"channel": "sns"})))
    assert ReviewResponse.model_validate(result).status == expected
