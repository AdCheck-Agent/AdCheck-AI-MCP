import json

from app.graph.nodes.review_llm import review_llm
from app.llm.alternative import Alternatives, Suggestion, _validate, risk_terms
from app.llm.client import set_review_model
from app.llm.criteria import CRITERIA, criteria_texts
from app.schemas.review import Evidence, Finding, ReviewResponse
from tests.test_review_llm import FakeModel, judgment, make_state

COMPANY_RULE = Evidence(
    document="YS컴퍼니 기업가치",
    section="브랜드 톤",
    snippet="특정 책상을 쓰지 않으면 아이의 성적이 떨어진다는 식의 표현을 쓰지 않는다.",
    rule_id="yscompany-corporate_values-006",
    version="v1",
)


def with_finding(**fields: object) -> str:
    base = json.loads(judgment())
    base["findings"][0].update(fields)
    return json.dumps(base, ensure_ascii=False)


def run(raw: str, state=None) -> tuple[dict, FakeModel]:
    model = FakeModel(raw)
    set_review_model(model)
    try:
        return review_llm(state or make_state()), model
    finally:
        set_review_model(None)


def test_company_finding_cites_the_company_rule() -> None:
    state = make_state()
    state["corporate_value_evidence"] = [COMPANY_RULE]
    raw = with_finding(category="corporate_value", quote="안 사면 평생 후회", evidence_ids=["C1"])
    result, _ = run(raw, state)
    assert result["risk"] == "yes"
    assert result["findings"][0].evidence == [
        COMPANY_RULE.model_copy(update={"source": "corporate"})
    ]


def test_evidence_carries_where_it_was_retrieved() -> None:
    state = make_state()
    state["corporate_value_evidence"] = [COMPANY_RULE]
    raw = with_finding(evidence_ids=["S1", "C1"])
    result, _ = run(raw, state)
    sources = [e.source for e in result["findings"][0].evidence]
    assert sources == ["social", "corporate"]
    response = ReviewResponse(
        status="revise", summary="s", findings=result["findings"], trace_id="trace_" + "0" * 32
    )
    dumped = response.model_dump(mode="json")["findings"][0]["evidence"]
    assert [e["source"] for e in dumped] == ["social", "corporate"]


def test_trigger_terms_outside_the_quote_are_dropped() -> None:
    result, _ = run(with_finding(trigger_terms=["탱크데이", "탁", "없는말", " "]))
    assert result["findings"][0].trigger_terms == ["탱크데이"]


def test_trigger_terms_stay_out_of_the_api_result() -> None:
    result, _ = run(with_finding(trigger_terms=["탱크데이"]))
    response = ReviewResponse(
        status="revise", summary="s", findings=result["findings"], trace_id="trace_" + "0" * 32
    )
    assert "trigger_terms" not in response.model_dump(mode="json")["findings"][0]


def finding(quote: str, terms: list[str]) -> Finding:
    return Finding(
        category="historical_context",
        severity="high",
        quote=quote,
        reason="박종철 사건을 연상시킵니다.",
        evidence=[Evidence(document="사례", section="보도", snippet="책상에 탁!이라는 표현")],
        needs_human_review=False,
        trigger_terms=terms,
    )


def kept_terms(found: Finding, suggestion: str) -> set[str]:
    state = make_state(with_hit=False) | {"findings": [found]}
    result, kept = _validate(
        state, Alternatives(suggestions=[Suggestion(index=0, suggestion=suggestion)])
    )
    assert result is not None
    return kept


def test_one_syllable_trigger_is_avoided_and_caught() -> None:
    found = finding("책상에 탁 치면 억 소리 나는 할인", ["탁", "억"])
    assert {"탁", "억"} <= risk_terms(found)
    assert kept_terms(found, "특별 할인! 탁 치면 놀라운 혜택") == {"탁"}
    # A syllable inside another word is not the trigger.
    assert kept_terms(found, "탁월한 품질의 책상 할인") == set()


def test_named_multi_syllable_trigger_is_caught_inside_a_word() -> None:
    found = finding("탱크데이 할인", ["탱크데이"])
    assert kept_terms(found, "탱크데이특가 진행") == {"탱크데이"}


def test_product_word_shared_with_the_case_is_not_avoided() -> None:
    # 책상에 is in both the ad and the case, but the judge named only 탁 and 억.
    found = finding("책상에 탁 치면 억 소리 나는 할인", ["탁", "억"])
    assert risk_terms(found) == {"탁", "억"}
    assert kept_terms(found, "튼튼한 책상에 어울리는 특별 할인") == set()


def test_shared_words_are_avoided_when_the_judge_named_none() -> None:
    found = finding("책상에 탁 치면 억 소리 나는 할인", [])
    assert risk_terms(found) == {"책상에"}


def test_company_values_criterion_is_offered() -> None:
    assert CRITERIA[-1].id == "K11"
    assert criteria_texts(["K11"]) == ["기업이 밝힌 가치·브랜드 원칙과의 충돌"]


def test_suggestion_prompt_carries_the_rule_that_was_broken() -> None:
    from app.llm.alternative import SYSTEM_PROMPT, build_prompt

    state = make_state(with_hit=False) | {
        "findings": [
            Finding(
                category="corporate_value",
                severity="medium",
                quote="안 사면 평생 후회",
                reason="불안으로 구매를 압박합니다.",
                evidence=[COMPANY_RULE],
                needs_human_review=False,
            )
        ]
    }
    findings = json.loads(build_prompt(state).split("<findings>\n")[1].split("\n</findings>")[0])
    assert findings[0]["rules"] == [COMPANY_RULE.snippet]
    assert "rules" in SYSTEM_PROMPT


def test_ordinary_ad_words_are_not_triggers() -> None:
    from app.llm.judge import trigger_terms

    quote = "5월 18일 기념 탱크데이 특별 할인, 오늘만 특가"
    assert trigger_terms(["5월 18일", "기념", "특별 할인", "오늘만 특가", "탱크데이"], quote) == [
        "5월 18일",
        "탱크데이",
    ]


def test_recheck_ignores_a_reflag_without_a_concrete_trigger() -> None:
    from tests.test_alternative import CLEAN, alt, judged_state, run_with

    vague = json.loads(CLEAN) | {
        "risk": "yes",
        "findings": [
            {
                "category": "historical_context",
                "severity": "medium",
                "quote": "봄맞이 감사 할인",
                "reason": "할인 행사라서 확인이 필요합니다.",
                "evidence_ids": ["S1"],
                "trigger_terms": ["할인"],
            }
        ],
    }
    model = FakeModel(alt((0, "봄맞이 감사 할인")), json.dumps(vague, ensure_ascii=False))
    result = run_with(model, judged_state("우리 매장 탱크데이 특가", "탱크데이"))
    assert result["status"] == "revise"
    assert result["findings"][0].suggestion == "봄맞이 감사 할인"


def test_suggestion_repeating_the_rest_of_the_ad_is_retried() -> None:
    from app.llm.alternative import _repeats_rest

    source = "안 사면 평생 후회, 오늘만 특가"
    assert _repeats_rest(source, "안 사면 평생 후회", "놓치지 마세요, 오늘만 특가") == {
        "오늘만 특가"
    }
    assert _repeats_rest(source, "안 사면 평생 후회", "놓치지 마세요") == set()


def test_rewrite_hint_names_the_words_the_recheck_objected_to() -> None:
    from tests.test_alternative import CLEAN, alt, flagged, judged_state, run_with

    model = FakeModel(
        alt((0, "기념일 특가")), flagged("기념일 특가"), alt((0, "봄맞이 감사 할인")), CLEAN
    )
    result = run_with(model, judged_state("우리 매장 탱크데이 특가", "탱크데이"))
    assert result["status"] == "revise"
    assert "['기념일']" in model.calls[2][1]


def test_trigger_punctuation_is_stripped() -> None:
    from app.llm.judge import trigger_terms

    assert trigger_terms(["탁!", "탱크데이,"], "탱크데이, 책상에 탁! 놓이는 신제품") == [
        "탁",
        "탱크데이",
    ]


def test_number_written_date_cannot_pass_when_evidence_has_the_date() -> None:
    from app.graph.state import initial_state
    from app.schemas.review import ReviewRequest

    state = initial_state(ReviewRequest(text="518원 할인 혜택", context={"channel": "sns"}))
    state["social_context_evidence"] = [
        Evidence(
            document="사례",
            section="보도",
            snippet="2026년 5월 18일 행사에 탱크데이 표현",
            rule_id="CASE",
        )
    ]
    clean = '{"risk": "no", "evidence_sufficient": true, "summary": "위험 없음", "findings": []}'
    result, _ = run(clean, state)
    assert result["risk"] == "uncertain" and "5월 18일" in result["summary"]


def test_written_out_date_and_unrelated_numbers_are_left_to_the_judge() -> None:
    from app.llm.dates import number_date_keys

    assert number_date_keys("5월 18일 새 텀블러") == set()  # a written date is judged as a date
    assert number_date_keys("518원 할인, 0518 특가") == {"5-18"}
    assert number_date_keys("1,000원 99% 할인 2026년") == set()
