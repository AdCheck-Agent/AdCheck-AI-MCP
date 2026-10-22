import httpx
from app.clients.business_mcp_client import BusinessMCPClient
from business_mcp.server import app
from fastapi.testclient import TestClient


def test_business_health_and_tool() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json()["service"] == "adcheck-business-mcp"
        response = client.post("/tools/search_recent_issue", json={"query": "최근 이슈"})
        assert response.status_code == 200
        assert response.json()["mock"] is True
        assert response.json()["results"] == []


async def test_agent_business_adapter() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://business-mcp:8002", timeout=10
    ) as http:
        result = await BusinessMCPClient(http).search_recent_issue("최근 이슈")
    assert result.mock and result.results == []
