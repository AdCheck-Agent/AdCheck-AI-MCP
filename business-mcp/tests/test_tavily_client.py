import asyncio
import json

import httpx
import pytest
from app.clients.business_mcp_client import RecentIssueResult
from business_mcp.clients.tavily_client import TavilyClient
from business_mcp.config import Settings
from pydantic import ValidationError


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, tavily_api_key="test-key", **overrides)


def item(number: int = 0) -> dict:
    return {
        "title": f"합성 기사 {number}",
        "url": f"https://example.com/{number}",
        "content": "테스트용 검색 내용",
        "score": 0.8,
        "published_date": "Tue, 20 Oct 2026 09:00:00 GMT",
    }


async def test_one_search_caps_and_metadata() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        assert str(request.url) == "https://api.tavily.com/search"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert body["max_results"] == 3
        assert body["include_answer"] is body["include_raw_content"] is False
        assert body["auto_parameters"] is False
        return httpx.Response(200, json={"results": [item(0), item(0), item(1), item(2), item(3)]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await TavilyClient(http, settings()).search("최근 이슈")
    assert len(calls) == 1
    assert result.status == "ok" and len(result.results) == 3
    assert result.results[0].source == "example.com"
    assert result.results[0].published_at.year == 2026
    assert result.results[0].retrieved_at.tzinfo is not None
    assert result.results[0].content_check == "not_checked"
    assert RecentIssueResult.model_validate(result.model_dump(mode="json")).status == "ok"


async def test_missing_key_never_calls_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No key must not cause any request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await TavilyClient(http, Settings(_env_file=None)).search("문구")
    assert result.status == "unavailable"


@pytest.mark.parametrize("code", [401, 429, 500, 302])
async def test_http_failure_no_retry_or_secret_leak(code: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            code,
            text="test-key secret provider body",
            headers={
                "Location": "https://example.com/redirect",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await TavilyClient(http, settings()).search("문구")
    assert result.status == "error" and calls == 1
    assert "test-key" not in result.model_dump_json()


@pytest.mark.parametrize(
    "body, status",
    [
        ({"results": []}, "empty"),
        ({"results": [{**item(), "content": " "}]}, "empty"),
        ({"results": [{**item(), "published_date": "unknown"}]}, "ok"),
        ({"unexpected": []}, "error"),
        ({"results": [{**item(), "url": "not-a-url"}]}, "error"),
    ],
)
async def test_empty_and_invalid_responses(body: dict, status: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as http:
        result = await TavilyClient(http, settings()).search("문구")
    assert result.status == status
    if result.results:
        assert result.results[0].published_at is None


async def test_total_deadline_no_retry() -> None:
    calls = 0

    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(10)
        return httpx.Response(200, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as http:
        result = await asyncio.wait_for(
            TavilyClient(http, settings(tavily_timeout_seconds=0.02)).search("문구"), timeout=1
        )
    assert result.status == "timeout" and calls == 1


async def test_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await TavilyClient(http, settings()).search("문구")
    assert result.status == "error"


@pytest.mark.parametrize(
    "overrides",
    [
        {"tavily_timeout_seconds": 6},
        {"tavily_max_results": 4},
        {"tavily_timeout_seconds": 0},
        {"tavily_max_results": 0},
    ],
)
def test_hard_caps(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        settings(**overrides)
