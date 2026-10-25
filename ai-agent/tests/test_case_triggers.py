import json

import pytest
from app.graph.nodes.rule_filter import find_rule_hits
from app.graph.state import initial_state
from app.llm.judge import GATED_SUMMARY, Judgment, build_catalog, resolve
from app.llm.triggers import case_applies
from app.schemas.review import Evidence, ReviewRequest

STARBUCKS = Evidence(
    document="스타벅스 2026년 5월 행사명·문구 논란",
    section="보도에서 확인한 사실",
    snippet="2026년 5월 18일 텀블러 행사에 탱크데이, 책상에 탁!이라는 표현이 사용돼 비판받았다.",
    rule_id="CASE-HIST-001",
    version="v1",
)
CRITERION = Evidence(
    document="사회적 맥락 검수 기준 v1",
    section="역사·기억 왜곡",
    snippet="역사적 사건을 이벤트명으로 소비하는 표현은 사람 검토가 필요하다.",
    rule_id="RULE-HIST-001",
    version="v1",
)


@pytest.mark.parametrize(
    ("rule_id", "text", "expected"),
    [
        # 한 단어만 겹치는 문구는 사례의 근거가 아니다
        ("CASE-HIST-001", "5월 18일 새 텀블러가 출시됩니다", False),
        ("CASE-HIST-001", "5월 18일부터 21일까지 사전 예약을 받습니다", False),
        ("CASE-HIST-001", "탱크톱 신상 입고, 여름 시즌 20% 할인", False),
        ("CASE-HIST-001", "탱크처럼 튼튼한 여행 가방을 소개합니다", False),
        # 결합이 있으면 표기가 달라도 적용된다
        ("CASE-HIST-001", "5월 18일 기념 탱크데이 특별 할인", True),
        ("CASE-HIST-001", "5.18 기념 탱크 데이 할인", True),
        ("CASE-HIST-001", "5·18 탱크톱 할인", True),
        ("CASE-HIST-001", "책상에 탁! 놓이는 신제품", True),
        ("CASE-HIST-001", "518원 할인 혜택", True),
        ("CASE-HIST-002", "625% 보습", True),
        ("CASE-HIST-002", "6월 25일 특가", False),
        ("CASE-HIST-003", "책상을 탁 치니 억 소리 나는 가격", True),
        ("CASE-HIST-003", "탁월한 품질, 억대 매출", False),
        # 조건이 없는 규칙·근거는 거르지 않는다
        ("RULE-HIST-001", "아무 문구", True),
        (None, "아무 문구", True),
    ],
)
def test_case_applies(rule_id: str | None, text: str, expected: bool) -> None:
    assert case_applies(rule_id, text) is expected


def judged(quote: str, evidence_ids: list[str], risk: str = "yes") -> Judgment:
    return Judgment.model_validate(
        json.loads(
            json.dumps(
                {
                    "risk": risk,
                    "evidence_sufficient": True,
                    "summary": "위험",
                    "findings": [
                        {
                            "category": "historical_context",
                            "severity": "high",
                            "quote": quote,
                            "reason": "단어가 겹침",
                            "evidence_ids": evidence_ids,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
    )


def state_for(text: str, *evidence: Evidence):
    state = initial_state(ReviewRequest(text=text, context={"channel": "sns"}))
    state["social_context_evidence"] = list(evidence)
    return state


def test_word_overlap_with_a_case_passes() -> None:
    state = state_for("탱크톱 신상 입고, 여름 시즌 20% 할인", STARBUCKS)
    result = resolve(judged("탱크톱", ["S1"]), state, build_catalog(state))
    assert result["risk"] == "no"
    assert result["findings"] == []
    assert result["summary"] == GATED_SUMMARY


def test_combination_keeps_the_finding() -> None:
    state = state_for("5월 18일 기념 탱크데이 특별 할인", STARBUCKS)
    result = resolve(judged("탱크데이", ["S1"]), state, build_catalog(state))
    assert result["risk"] == "yes"
    assert result["findings"][0].evidence[0].rule_id == "CASE-HIST-001"


def test_gated_case_is_dropped_but_other_evidence_stays() -> None:
    state = state_for("5월 18일 새 텀블러가 출시됩니다", STARBUCKS, CRITERION)
    result = resolve(judged("5월 18일", ["S1", "S2"]), state, build_catalog(state))
    assert result["risk"] == "yes"
    assert [e.rule_id for e in result["findings"][0].evidence] == ["RULE-HIST-001"]


def test_gate_does_not_hide_a_banned_expression() -> None:
    state = state_for("5월 18일 새 텀블러, 안 사면 평생 후회", STARBUCKS)
    state["rule_hits"] = find_rule_hits(state["source_text"])
    result = resolve(judged("5월 18일", ["S1"]), state, build_catalog(state))
    assert result["risk"] == "uncertain"
    assert state["rule_hits"]


def test_judgment_without_evidence_is_not_a_gate_case() -> None:
    # 근거를 아예 인용하지 않은 지적은 기존 규칙대로 사람 검토다
    state = state_for("탱크톱 입고", STARBUCKS)
    result = resolve(judged("탱크톱", []), state, build_catalog(state))
    assert result["risk"] == "uncertain"
