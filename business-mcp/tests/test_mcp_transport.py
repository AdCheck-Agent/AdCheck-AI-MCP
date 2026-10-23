import json
from contextlib import asynccontextmanager

import business_mcp.server as server_module
import httpx
import pytest
from business_mcp.clients.tavily_client import TavilyClient
from business_mcp.config import Settings
from business_mcp.schemas import SearchResult
from business_mcp.server import create_app
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@asynccontextmanager
async def mcp_session(settings: Settings | None = None):
    app = create_app(settings or Settings(_env_file=None, tavily_api_key=None))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8002"
        ) as http:
            async with streamable_http_client("http://localhost:8002/mcp", http_client=http) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session


async def test_tool_discovery_and_missing_key() -> None:
    async with mcp_session() as session:
        tools = (await session.list_tools()).tools
        assert sorted(tool.name for tool in tools) == ["save_checkpoint", "search_recent_issue"]
        tools = [t for t in tools if t.name == "search_recent_issue"]
        query_schema = tools[0].inputSchema["properties"]["query"]
        assert query_schema["minLength"] == 1
        assert query_schema["maxLength"] == 400
        assert "status" in tools[0].outputSchema["properties"]
        response = await session.call_tool("search_recent_issue", {"query": "최근 이슈"})
    assert response.isError is True
    result = SearchResult.model_validate(response.structuredContent)
    assert result.status == "unavailable"
    assert result.results == [] and result.related_criteria == [] and result.mock is False


@pytest.mark.parametrize("status", ["ok", "empty", "timeout", "unavailable", "error"])
async def test_outcome_and_full_result_preserved(monkeypatch, status: str) -> None:
    expected = SearchResult(
        status=status, related_criteria=["테스트용 기준"], message="테스트 검색 상태"
    )
    calls = []

    async def search(query, settings):
        calls.append(query)
        return expected

    monkeypatch.setattr(server_module, "search_recent_issue", search)
    async with mcp_session() as session:
        response = await session.call_tool("search_recent_issue", {"query": "  확인할 사실  "})
    assert calls == ["확인할 사실"]
    assert response.isError is (status in {"timeout", "unavailable", "error"})
    assert response.structuredContent == expected.model_dump(mode="json")
    assert json.loads(response.content[0].text) == response.structuredContent


@pytest.mark.parametrize("arguments", [{}, {"query": ""}, {"query": "  "}, {"query": "가" * 401}])
async def test_invalid_input_does_not_search(monkeypatch, arguments) -> None:
    calls = []

    async def search(query, settings):
        calls.append(query)
        return SearchResult(status="empty", message="unused")

    monkeypatch.setattr(server_module, "search_recent_issue", search)
    async with mcp_session() as session:
        response = await session.call_tool("search_recent_issue", arguments)
    assert response.isError is True
    assert calls == []


async def test_mcp_to_provider_wire_contract(monkeypatch) -> None:
    calls = []

    def provider(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "합성 기사",
                        "url": "https://example.com/article",
                        "content": "합성 검색 근거",
                        "score": 0.7,
                        "published_date": "2026-10-20T12:00:00Z",
                    }
                ]
            },
        )

    async def search(query, settings):
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
            return await TavilyClient(http, settings).search(query)

    monkeypatch.setattr(server_module, "search_recent_issue", search)
    settings = Settings(_env_file=None, tavily_api_key="fake-key")
    async with mcp_session(settings) as session:
        response = await session.call_tool("search_recent_issue", {"query": "공개 사실"})
    assert response.isError is False
    result = SearchResult.model_validate(response.structuredContent)
    assert len(calls) == 1 and calls[0]["query"] == "공개 사실"
    assert result.status == "ok" and len(result.results) == 1
    issue = result.results[0]
    assert str(issue.url) == "https://example.com/article"
    assert issue.title == "합성 기사" and issue.snippet == "합성 검색 근거"
    assert issue.source == "example.com" and issue.score == 0.7
    assert issue.published_at is not None and issue.retrieved_at.tzinfo is not None
    assert issue.content_check == "not_checked"


async def test_untrusted_host_rejected() -> None:
    app = create_app(Settings(_env_file=None, tavily_api_key=None))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
            response = await http.post(
                "http://untrusted.example/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
    assert response.status_code == 421
