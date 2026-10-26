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


CLEAN = json.dumps(
    {"risk": "no", "evidence_sufficient": True, "summary": "위험 없음", "findings": []},
    ensure_ascii=False,
)  # 고친 광고를 다시 볼 때 판정의 응답


def flagged(quote: str, risk: str = "yes") -> str:
    """고친 광고에 위험한 표현이 남아 있을 때 판정의 응답."""
    finding = {
        "category": "historical_context",
        "severity": "high",
        "quote": quote,
        "reason": "수정안에도 같은 사건이 연상됩니다.",
        "evidence_ids": ["S1"],
        "trigger_terms": [quote.split()[0]],  # 재검사는 문제 삼은 단어를 짚어야 한다
        "needs_human_review": False,
    }
    return json.dumps(
        {"risk": risk, "evidence_sufficient": True, "summary": "다시 지적", "findings": [finding]},
        ensure_ascii=False,
    )


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
    model = FakeModel(alt((0, "봄맞이 감사 할인")), CLEAN)
    set_review_model(model)
    result = generate_alternative(make_state())
    assert result["status"] == "revise"
    assert result["findings"][0].suggestion == "봄맞이 감사 할인"
    assert result["summary"] == "수정이 필요합니다."
    assert "탱크데이" in model.calls[0][1]


@pytest.mark.parametrize(
    "raw",
    [
        alt((0, "탱크데이 특별전")),  # 원래 인용을 다시 씀
        alt((0, "지금 놓치면 안 사면 평생 후회")),  # 금기어를 다시 씀
        alt((1, "엉뚱한 index")),  # 0번 지적에 대한 답이 없음
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
    model = FakeModel("형식 오류", alt((0, "봄맞이 감사 할인")), CLEAN)
    set_review_model(model)
    assert generate_alternative(make_state())["status"] == "revise"
    assert len(model.calls) == 3


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
        FakeModel(
            json.dumps(judged, ensure_ascii=False),
            alt((0, "봄맞이 감사 할인"), (1, "지금 만나보세요")),
            CLEAN,
        )
    )
    graph = graph_module.build_graph()
    result = graph.invoke(initial_state(ReviewRequest(text=TEXT, context={"channel": "sns"})))
    response = ReviewResponse.model_validate(result)
    assert response.status == "revise"
    assert response.findings[0].suggestion == "봄맞이 감사 할인"
    # TEXT에는 모델이 지적하지 않은 금기어도 있다. 이것도 목록에 들어가고 수정안을 받는다.
    banned = response.findings[1]
    assert (banned.detection_type, banned.quote) == ("SEMANTIC", "안 사면 평생 후회")
    assert banned.suggestion == "지금 만나보세요"


def risky_state() -> ReviewState:
    state = initial_state(
        ReviewRequest(text="5월 18일 기념 탱크데이 특가", context={"channel": "sns"})
    )
    state["findings"] = [
        Finding(
            category="historical_context",
            severity="high",
            quote="5월 18일 기념 탱크데이",
            reason="날짜와 결합",
            evidence=[
                Evidence(
                    document="사례",
                    section="사실",
                    snippet="2026년 5월 18일 행사에 탱크데이 표현이 사용돼 비판받았다",
                )
            ],
            needs_human_review=False,
        )
    ]
    state["summary"] = "수정 필요"
    return state


def test_prompt_tells_the_model_which_words_to_avoid() -> None:
    from app.llm.alternative import risk_terms

    assert risk_terms(risky_state()["findings"][0]) == {"5월", "18일", "탱크데이"}


def test_suggestion_keeping_a_flagged_word_is_retried_once() -> None:
    model = FakeModel(alt((0, "특별한 날 탱크데이")), alt((0, "감사 특가")), CLEAN)
    result = generate_alternative_with(model)
    assert result["status"] == "revise"
    assert result["findings"][0].suggestion == "감사 특가"
    assert len(model.calls) == 3
    assert "탱크데이" in model.calls[1][1]  # 재시도 안내에 뺄 단어가 들어간다


def test_suggestion_still_keeping_the_word_goes_to_a_person() -> None:
    model = FakeModel(alt((0, "5월 18일 감사 특가")), alt((0, "5월 18일 봄 특가")))
    result = generate_alternative_with(model)
    assert result["status"] == "needs_review"
    assert all(f.needs_human_review for f in result["findings"])


def generate_alternative_with(model: FakeModel) -> dict:
    set_review_model(model)
    return generate_alternative(risky_state())


def price_state() -> ReviewState:
    """'518원'이 5·18로 지적된다. 근거의 날짜 표기는 인용과 다르다."""
    state = initial_state(ReviewRequest(text="518원 할인 혜택", context={"channel": "sns"}))
    state["findings"] = [
        Finding(
            category="historical_context",
            severity="medium",
            quote="518원 할인 혜택",
            reason="5·18 민주화운동과 관련된 날짜를 연상시킬 수 있습니다.",
            evidence=[
                Evidence(
                    document="기준",
                    section="역사",
                    snippet="5·18민주화운동은 1980년 5월 광주에서 전개된 민주화운동이다",
                )
            ],
            needs_human_review=False,
        )
    ]
    state["summary"] = "수정 필요"
    return state


def test_date_keys_ignore_how_the_date_is_written() -> None:
    from app.llm.alternative import date_keys

    for text in ("5월 18일", "5·18민주화운동", "5.18", "05-18", "518원", "5ㆍ18"):
        assert date_keys(text) == {"5-18"}, text
    assert date_keys("1980년 2026년 1,000원 99% 할인") == set()


def test_prompt_names_the_date_even_when_spelled_differently() -> None:
    model = FakeModel(alt((0, "특별 할인 혜택")), CLEAN)
    set_review_model(model)
    assert generate_alternative(price_state())["status"] == "revise"
    assert "5월 18일" in model.calls[0][1]


@pytest.mark.parametrize("kept", ["518원 특별 할인 혜택", "5.18 할인 혜택", "5월 18일 특가"])
def test_suggestion_keeping_the_flagged_date_is_retried(kept: str) -> None:
    model = FakeModel(alt((0, kept)), alt((0, "특별 할인 혜택")), CLEAN)
    set_review_model(model)
    result = generate_alternative(price_state())
    assert result["status"] == "revise"
    assert result["findings"][0].suggestion == "특별 할인 혜택"
    assert "5월 18일" in model.calls[1][1]  # 재시도 안내에 뺄 날짜가 들어간다


def test_suggestion_still_keeping_the_flagged_date_goes_to_a_person() -> None:
    set_review_model(FakeModel(alt((0, "518원 특별 할인 혜택")), alt((0, "5·18 할인 혜택"))))
    result = generate_alternative(price_state())
    assert result["status"] == "needs_review"
    assert result["findings"][0].needs_human_review is True


def judged_state(text: str, quote: str) -> ReviewState:
    """검색된 근거를 담은 revise 상태. 고친 광고를 다시 판정할 수 있게 한다."""
    state = initial_state(ReviewRequest(text=text, context={"channel": "sns"}))
    evidence = Evidence(document="기준 v1", section="역사", snippet="사건 소비 금지")
    state["social_context_evidence"] = [evidence]
    state["findings"] = [
        Finding(
            category="historical_context",
            severity="high",
            quote=quote,
            reason="역사적 사건을 연상시킬 수 있습니다.",
            evidence=[evidence],
            needs_human_review=False,
        )
    ]
    state["summary"] = "수정 필요"
    return state


def run_with(model: FakeModel, state: ReviewState) -> dict:
    set_review_model(model)
    return generate_alternative(state)


def test_fixed_ad_is_judged_again_with_the_suggestion_in_place() -> None:
    model = FakeModel(alt((0, "봄맞이 감사 할인")), CLEAN)
    state = judged_state("우리 매장 탱크데이 특가", "탱크데이")
    assert run_with(model, state)["status"] == "revise"
    assert "우리 매장 봄맞이 감사 할인 특가" in model.calls[1][1]


def test_suggestion_flagged_after_applying_is_rewritten_once() -> None:
    model = FakeModel(
        alt((0, "기념일 특가")),
        flagged("기념일 특가"),
        alt((0, "봄맞이 감사 할인")),
        CLEAN,
    )
    result = run_with(model, judged_state("우리 매장 탱크데이 특가", "탱크데이"))
    assert result["status"] == "revise"
    assert result["findings"][0].suggestion == "봄맞이 감사 할인"
    assert "기념일 특가" in model.calls[2][1]  # 다시 쓰기 안내에 탈락한 수정안이 들어간다


def test_suggestion_still_flagged_after_the_rewrite_goes_to_a_person() -> None:
    model = FakeModel(
        alt((0, "기념일 특가")),
        flagged("기념일 특가"),
        alt((0, "그날 특가")),
        flagged("그날 특가"),
    )
    result = run_with(model, judged_state("우리 매장 탱크데이 특가", "탱크데이"))
    assert result["status"] == "needs_review"
    assert result["findings"][0].needs_human_review is True
    assert result["findings"][0].suggestion is None


def test_wording_the_suggestion_did_not_touch_cannot_reject_it() -> None:
    model = FakeModel(alt((0, "봄맞이 감사 할인")), flagged("우리 매장"))
    result = run_with(model, judged_state("우리 매장 탱크데이 특가", "탱크데이"))
    assert result["status"] == "revise"
    assert len(model.calls) == 2


def test_uncertain_after_applying_does_not_reject_the_suggestion() -> None:
    model = FakeModel(alt((0, "봄맞이 감사 할인")), flagged("봄맞이 감사 할인", "uncertain"))
    result = run_with(model, judged_state("우리 매장 탱크데이 특가", "탱크데이"))
    assert result["status"] == "revise"
    assert len(model.calls) == 2


def test_failed_recheck_goes_to_a_person() -> None:
    model = FakeModel(alt((0, "봄맞이 감사 할인")), TimeoutError("timeout"))
    result = run_with(model, judged_state("우리 매장 탱크데이 특가", "탱크데이"))
    assert result["status"] == "needs_review"
    assert result["findings"][0].suggestion is None
