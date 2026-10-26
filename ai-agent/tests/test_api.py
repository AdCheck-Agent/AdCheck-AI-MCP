import asyncio
import json

import httpx
import pytest
from app.core.config import get_settings
from app.graph.graph import build_graph
from app.graph.state import initial_state
from app.main import app
from app.schemas.review import ReviewAccepted, ReviewRequest, ReviewResponse
from app.services.review import run_review
from fastapi.testclient import TestClient


def test_health_reports_what_settings_switched_off(monkeypatch, caplog) -> None:
    monkeypatch.setenv("RAG_RETRIEVAL_ENABLED", "false")
    monkeypatch.setenv("CHECKPOINT_ENABLED", "false")
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "adcheck-ai-agent",
        "features": {"review_model": "mock", "rag_retrieval": False, "checkpoint": False},
    }
    assert "OPENAI_API_KEY is not set" in caplog.text
    assert "RAG_RETRIEVAL_ENABLED is false" in caplog.text
    assert "CHECKPOINT_ENABLED is false" in caplog.text


def test_health_with_everything_on(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("RAG_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("CHECKPOINT_ENABLED", "true")
    get_settings.cache_clear()
    with TestClient(app) as client:
        features = client.get("/health").json()["features"]
    assert features == {"review_model": "openai", "rag_retrieval": True, "checkpoint": True}
    assert "is not set" not in caplog.text and "is false" not in caplog.text


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


def test_review_acceptance_and_unique_trace(caplog) -> None:
    caplog.set_level("INFO")
    payload = {
        "text": "5월 18일을 기념해 오늘만 특별 할인! 탱크처럼 강력한 혜택을 만나보세요.",
        "context": {"channel": "sns", "campaign_name": "봄 프로모션", "company_id": "company_demo"},
    }
    with TestClient(app) as client:
        first = client.post("/api/v1/reviews", json=payload)
        second = client.post("/api/v1/reviews", json=payload)
    assert first.status_code == second.status_code == 202
    accepted = ReviewAccepted.model_validate(first.json())
    assert accepted.status == "accepted"
    assert set(first.json()) == {"status", "trace_id"}
    assert accepted.trace_id != second.json()["trace_id"]
    assert "location" not in first.headers
    assert f"review completed trace_id={accepted.trace_id}" in caplog.text


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


class SlowGraph:
    async def ainvoke(self, state: dict) -> dict:
        await asyncio.sleep(5)
        return state


class BrokenGraph:
    async def ainvoke(self, state: dict) -> dict:
        raise RuntimeError("boom")


PAYLOAD = {"text": "새로운 상품을 소개합니다", "context": {"channel": "sns"}}


def test_background_timeout_keeps_202_and_logs_trace(monkeypatch, caplog) -> None:
    monkeypatch.setenv("REVIEW_TIMEOUT_SECONDS", "0.05")
    from app.core.config import get_settings

    get_settings.cache_clear()
    with TestClient(app) as client:
        app.state.review_graph = SlowGraph()
        response = client.post("/api/v1/reviews", json=PAYLOAD)
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert response.json()["trace_id"] in caplog.text
    assert "code=review_timeout" in caplog.text


def test_background_failure_keeps_202_without_exposing_internals(caplog) -> None:
    with TestClient(app) as client:
        app.state.review_graph = BrokenGraph()
        response = client.post("/api/v1/reviews", json=PAYLOAD)
    assert response.status_code == 202
    assert response.json()["trace_id"] in caplog.text
    assert "code=review_failed" in caplog.text
    assert "boom" not in response.text


async def test_background_execution_preserves_validated_review_result() -> None:
    state = initial_state(ReviewRequest.model_validate(PAYLOAD))
    result = await run_review(state, build_graph(), timeout_seconds=1)
    assert isinstance(result, ReviewResponse)
    assert result.status == "needs_review"
    assert "[MOCK]" in result.summary
    assert result.findings == []
    assert result.trace_id == state["trace_id"]


async def test_invalid_background_result_is_logged(caplog) -> None:
    class InvalidGraph:
        async def ainvoke(self, state):
            return {"status": "pass"}

    state = initial_state(ReviewRequest.model_validate(PAYLOAD))
    assert await run_review(state, InvalidGraph(), timeout_seconds=1) is None
    assert "code=review_failed" in caplog.text
    assert state["trace_id"] in caplog.text


async def test_202_body_is_sent_before_background_work_finishes() -> None:
    # TestClient와 httpx의 ASGI transport는 응답 본문을 보낸 뒤에도 BackgroundTasks를
    # 기다린다. HTTP 경계를 테스트하려고 ASGI send를 직접 관찰한다.
    release = asyncio.Event()
    both_started = asyncio.Event()
    sent = [asyncio.Event(), asyncio.Event()]
    messages = [[], []]
    states = []
    completed = []

    class GatedGraph:
        async def ainvoke(self, state):
            index = int(state["source_text"][-1])
            assert sent[index].is_set()
            states.append(state)
            if len(states) == 2:
                both_started.set()
            await release.wait()
            completed.append(state["trace_id"])
            return {**state, "status": "pass", "summary": "완료"}

    async def request(index: int):
        body = json.dumps({**PAYLOAD, "text": f"광고 {index}"}).encode()
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            messages[index].append(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                sent[index].set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/reviews",
            "raw_path": b"/api/v1/reviews",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "server": ("test", 80),
            "client": ("test", 12345),
        }
        await app(scope, receive, send)

    async with app.router.lifespan_context(app):
        app.state.review_graph = GatedGraph()
        tasks = [asyncio.create_task(request(i)) for i in range(2)]
        try:
            await asyncio.wait_for(both_started.wait(), timeout=2)
            assert not completed
            assert all(not task.done() for task in tasks)
            accepted = []
            for response_messages in messages:
                assert response_messages[0]["status"] == 202
                body = b"".join(
                    message["body"]
                    for message in response_messages
                    if message["type"] == "http.response.body"
                )
                payload = json.loads(body)
                assert set(payload) == {"status", "trace_id"}
                accepted.append(ReviewAccepted.model_validate(payload))
            assert accepted[0].trace_id != accepted[1].trace_id
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.get("/health")).status_code == 200
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        assert set(completed) == {response.trace_id for response in accepted}
        assert {state["source_text"] for state in states} == {"광고 0", "광고 1"}


def test_no_job_polling_endpoint() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/reviews/job_example").status_code == 404
        assert set(client.get("/openapi.json").json()["paths"]["/api/v1/reviews"]) == {"post"}
