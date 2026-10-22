from contextlib import asynccontextmanager

import business_mcp.server as server_module
import httpx
import pytest
from app.clients.business_mcp_client import BusinessMCPTransportClient
from business_mcp.config import Settings
from business_mcp.schemas import SearchResult
from business_mcp.server import create_app


@asynccontextmanager
async def client_for(search):
    server_module.search_recent_issue = search
    app = create_app(Settings(_env_file=None, tavily_api_key=None))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8002"
        ) as http:
            yield BusinessMCPTransportClient("http://localhost:8002/mcp", http_client=http)


@pytest.fixture(autouse=True)
def restore_search():
    original = server_module.search_recent_issue
    yield
    server_module.search_recent_issue = original


@pytest.mark.parametrize("status", ["ok", "empty", "timeout", "unavailable", "error"])
async def test_status_is_preserved_even_when_the_tool_reports_an_error(status: str) -> None:
    async def search(query, settings):
        return SearchResult(status=status, message="테스트", related_criteria=["기준"])

    async with client_for(search) as client:
        result = await client.search_recent_issue("확인할 사실")
    assert result.status == status
    assert result.related_criteria == ["기준"]


async def test_query_reaches_the_tool_trimmed() -> None:
    seen = []

    async def search(query, settings):
        seen.append(query)
        return SearchResult(status="empty", message="없음")

    async with client_for(search) as client:
        await client.search_recent_issue("  공개 사실  ")
    assert seen == ["공개 사실"]


async def test_invalid_input_is_reported_as_value_error() -> None:
    async def search(query, settings):
        raise AssertionError("must not search")

    async with client_for(search) as client:
        with pytest.raises(ValueError):
            await client.search_recent_issue("가" * 401)


async def test_unreachable_server_is_reported_as_value_error() -> None:
    client = BusinessMCPTransportClient("http://127.0.0.1:9/mcp", timeout=1)
    with pytest.raises((ValueError, TimeoutError)):
        await client.search_recent_issue("확인할 사실")
