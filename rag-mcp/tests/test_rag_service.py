import httpx
from app.clients.rag_mcp_client import RagMCPClient
from fastapi.testclient import TestClient
from rag_mcp.server import create_app


class EmptyStore:
    async def search(self, *args, **kwargs):
        return []


app = create_app(store=EmptyStore())


def test_rag_health_and_tools() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json()["service"] == "adcheck-rag-mcp"
        for path, payload in [
            ("search_social_context", {"query": "사회적 맥락"}),
            ("search_corporate_value", {"query": "윤리적 생산", "company_id": "demo"}),
        ]:
            response = client.post(f"/tools/{path}", json=payload)
            assert response.status_code == 200
            assert response.json()["mock"] is False
            assert response.json()["status"] == "empty"
            assert response.json()["evidence"] == []
        assert client.post("/tools/search_social_context", json={"query": " "}).status_code == 422
        assert (
            client.post("/tools/search_corporate_value", json={"query": "문구"}).status_code == 422
        )


async def test_agent_rag_adapter() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://rag-mcp:8001", timeout=10
    ) as http:
        client = RagMCPClient(http)
        assert not (await client.search_social_context("문구")).mock
        result = await client.search_corporate_value("문구", "demo")
        assert not result.mock and result.evidence == []


async def test_agent_rag_adapter_propagates_http_error() -> None:
    import pytest

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://rag-mcp:8001", timeout=10
    ) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await RagMCPClient(http).search_corporate_value("문구", "")
