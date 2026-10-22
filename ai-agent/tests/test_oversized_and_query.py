import json

import pytest
from app.clients.rag_mcp_client import RetrievalEvidence, RetrievalResult
from app.graph.nodes.review_llm import review_llm
from app.graph.nodes.validate_result import validate_result
from app.graph.state import initial_state
from app.llm.client import set_review_model
from app.llm.judge import clean_query
from app.schemas.review import ReviewRequest

TEXT = "5월 18일 기념 탱크데이 특별 할인"


class FakeModel:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)

    def generate(self, system: str, user: str) -> str:
        return self.responses.pop(0)


def judged(**kw) -> str:
    data = {"risk": "no", "evidence_sufficient": True, "summary": "위험 없음", "findings": []}
    return json.dumps({**data, **kw}, ensure_ascii=False)


def state_with(corporate_status: str = "too_large"):
    state = initial_state(ReviewRequest(text="새 상품 안내", context={"channel": "sns"}))
    state["social_context_evidence"] = [
        RetrievalEvidence(document="기준", section="역사", snippet="사건 소비 금지")
    ]
    state["corporate_value_result"] = RetrievalResult(
        status=corporate_status, mock=False, message="too large"
    )
    return state


def test_oversized_attachment_never_ends_in_pass_and_says_why() -> None:
    set_review_model(FakeModel(judged()))
    result = review_llm(state_with())
    assert result["risk"] == "uncertain"
    assert result["evidence_sufficient"] is False
    assert "너무 커서" in result["summary"] and "기업 가치" in result["summary"]


def test_oversized_attachment_keeps_a_clear_social_risk() -> None:
    finding = {
        "category": "historical_context",
        "severity": "high",
        "quote": "새 상품",
        "reason": "테스트",
        "evidence_ids": ["S1"],
    }
    set_review_model(FakeModel(judged(risk="yes", summary="수정 필요", findings=[finding])))
    result = review_llm(state_with())
    assert result["risk"] == "yes"
    assert result["summary"].startswith("기업 가치 첨부 문서가 너무 커서")


def test_normal_result_is_untouched() -> None:
    set_review_model(FakeModel(judged()))
    result = review_llm(state_with("ok"))
    assert result["risk"] == "no" and result["summary"] == "위험 없음"


def test_validator_blocks_pass_with_oversized_attachment() -> None:
    state = state_with()
    state.update(status="pass", evidence_sufficient=True, risk="no", summary="통과")
    assert validate_result(state)["status"] == "needs_review"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("탱크데이 논란 https://evil.example.com/a?x=1", "탱크데이 논란"),
        ("담당자 kim@example.com 연락처 확인", "담당자 연락처 확인"),
        ("고객센터 010-1234-5678 번호 논란", "고객센터 번호 논란"),
        ("  탱크데이   이벤트  논란 ", "탱크데이 이벤트 논란"),
        ("https://example.com", None),
        ("", None),
        ("가" * 401, None),
        ("5월 18일 기념 탱크데이 특별 할인 논란", None),
    ],
)
def test_clean_query(raw: str, expected: str | None) -> None:
    assert clean_query(raw, TEXT) == expected
