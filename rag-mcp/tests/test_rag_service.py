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


async def test_adapter_preserves_related_criteria_and_result_metadata() -> None:
    payload = {
        "status": "ok",
        "mock": False,
        "message": "테스트용 검색 결과",
        "related_criteria": ["역사적 사건·상징의 상업적 소비 가능성"],
        "evidence": [
            {
                "document": "기준",
                "section": "역사 존중",
                "snippet": "검수 기준 원문",
                "rule_id": "RULE-1",
                "version": "v1",
                "document_id": "doc1",
                "chunk_id": "chunk1",
                "source_urls": ["https://example.com/source"],
                "score": 0.8,
            }
        ],
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
        base_url="http://rag-mcp:8001",
    ) as http:
        client = RagMCPClient(http)
        for result in (
            await client.search_social_context("문구"),
            await client.search_corporate_value("문구", "demo"),
        ):
            assert result.related_criteria == payload["related_criteria"]
            assert result.message == payload["message"]
            assert result.evidence[0].source_urls == payload["evidence"][0]["source_urls"]
            assert result.evidence[0].score == 0.8


async def test_too_large_attachment_is_a_status_not_an_error() -> None:
    from rag_mcp.errors import AttachedDocumentsTooLarge

    class LargeStore:
        async def search(self, *args, **kwargs):
            raise AttachedDocumentsTooLarge(40000, 30000)

    large = create_app(store=LargeStore())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=large), base_url="http://rag-mcp:8001"
    ) as http:
        response = await http.post(
            "/tools/search_corporate_value",
            json={"query": "문구", "company_id": "demo", "document_ids": ["doc"]},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "too_large"
        assert response.json()["evidence"] == []
        result = await RagMCPClient(http).search_corporate_value("문구", "demo")
        assert result.status == "too_large" and result.evidence == []


async def test_agent_adapter_forwards_attached_document_ids() -> None:
    calls = []

    class RecordingStore:
        async def search(self, query, **kwargs):
            calls.append(kwargs)
            return []

    recording = create_app(store=RecordingStore())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=recording), base_url="http://rag-mcp:8001"
    ) as http:
        client = RagMCPClient(http)
        await client.search_corporate_value("문구", "demo", document_ids=["demo-ethics"])
        await client.search_corporate_value("문구", "demo")
    assert calls[0]["document_ids"] == ["demo-ethics"]
    assert calls[1]["document_ids"] is None
