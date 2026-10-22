import business_mcp.server as server_module
import httpx
import pytest
from app.clients.business_mcp_client import BusinessMCPClient
from business_mcp.clients.tavily_client import TavilyClient
from business_mcp.config import Settings
from business_mcp.schemas import SearchResult
from business_mcp.server import create_app
from fastapi.testclient import TestClient


def test_business_health_and_tool(app) -> None:
    with TestClient(app) as client:
        assert client.get("/health").json()["service"] == "adcheck-business-mcp"
        response = client.post("/tools/search_recent_issue", json={"query": "최근 이슈"})
        assert response.status_code == 503
        assert response.json()["mock"] is False
        assert response.json()["status"] == "unavailable"
        assert response.json()["results"] == []
        assert response.json()["related_criteria"] == []


async def test_agent_business_adapter(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://business-mcp:8002", timeout=10
    ) as http:
        result = await BusinessMCPClient(http).search_recent_issue("최근 이슈")
    assert result.status == "unavailable" and result.results == []
    assert result.related_criteria == []


@pytest.mark.parametrize("query", ["", "  ", "가" * 401])
def test_invalid_query(app, query: str) -> None:
    with TestClient(app) as client:
        response = client.post("/tools/search_recent_issue", json={"query": query})
    assert response.status_code == 422


@pytest.fixture
def app():
    return create_app(Settings(_env_file=None, tavily_api_key=None))


async def test_agent_to_tool_to_provider_wire_contract(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def provider(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "합성 기사",
                        "url": "https://example.com/article",
                        "content": "합성 검색 근거",
                        "score": 0.7,
                    }
                ]
            },
        )

    async def search(query: str, settings: Settings) -> SearchResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
            config = Settings(_env_file=None, tavily_api_key="fake-key")
            return await TavilyClient(http, config).search(query)

    monkeypatch.setattr(server_module, "search_recent_issue", search)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://business-mcp:8002"
    ) as http:
        result = await BusinessMCPClient(http).search_recent_issue("최근 이슈")
    assert calls == 1 and result.status == "ok"
    assert str(result.results[0].url) == "https://example.com/article"
    assert result.results[0].content_check == "not_checked"


@pytest.mark.parametrize(
    "status, code",
    [
        ("empty", 200),
        ("error", 502),
        ("unavailable", 503),
        ("timeout", 504),
    ],
)
async def test_http_outcome_contract(
    app, monkeypatch: pytest.MonkeyPatch, status: str, code: int
) -> None:
    async def search(query: str, settings: Settings) -> SearchResult:
        return SearchResult(status=status, results=[], message="테스트 검색 상태")

    monkeypatch.setattr(server_module, "search_recent_issue", search)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://business-mcp:8002"
    ) as http:
        response = await http.post("/tools/search_recent_issue", json={"query": "확인할 사실"})
        assert response.status_code == code
        assert response.json()["results"] == []
        result = await BusinessMCPClient(http).search_recent_issue("확인할 사실")
        assert result.status == status and result.results == []
