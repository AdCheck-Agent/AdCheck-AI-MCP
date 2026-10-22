import pytest
from app.main import app
from app.schemas.review import ReviewResponse
from fastapi.testclient import TestClient


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "adcheck-ai-agent"}


@pytest.mark.parametrize("text", ["", " \n\t ", "가" * 2001])
def test_invalid_text(text: str) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/reviews", json={"text": text, "context": {"channel": "sns"}}
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "context", [{}, {"channel": "email"}, {"channel": "sns", "campaign_name": "가" * 101}]
)
def test_invalid_context(context: dict) -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/reviews", json={"text": "새로운 상품", "context": context})
    assert response.status_code == 422


def test_review_response_and_unique_trace() -> None:
    payload = {
        "text": "5월 18일을 기념해 오늘만 특별 할인! 탱크처럼 강력한 혜택을 만나보세요.",
        "context": {"channel": "sns", "campaign_name": "봄 프로모션", "company_id": "company_demo"},
    }
    with TestClient(app) as client:
        first = client.post("/api/v1/reviews", json=payload)
        second = client.post("/api/v1/reviews", json=payload)
    assert first.status_code == second.status_code == 200
    result = ReviewResponse.model_validate(first.json())
    assert result.status == "needs_review"
    assert "[MOCK]" in result.summary
    assert result.findings == []
    assert result.trace_id != second.json()["trace_id"]


def test_finding_schema() -> None:
    result = ReviewResponse.model_validate(
        {
            "status": "revise",
            "summary": "테스트 fixture",
            "trace_id": "trace_" + "a" * 32,
            "findings": [
                {
                    "category": "historical_context",
                    "severity": "high",
                    "quote": "fixture 문구",
                    "reason": "fixture 이유",
                    "evidence": [
                        {
                            "document": "테스트 전용 문서",
                            "section": "fixture",
                            "snippet": "합성 근거",
                        }
                    ],
                    "suggestion": "fixture 수정안",
                    "needs_human_review": True,
                }
            ],
        }
    )
    assert result.findings[0].evidence[0].document == "테스트 전용 문서"
