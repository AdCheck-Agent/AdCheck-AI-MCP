"""Agent 코드와 상관없이 MCP SDK를 직접 실행해 본다."""

from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from rag_mcp.errors import StorageUnavailable
from rag_mcp.schemas import SearchResult
from rag_mcp.server import create_app

DATA = Path(__file__).resolve().parents[1] / "data" / "corporate"


async def test_uploaded_demo_documents_through_mcp(db_store):
    """실제 PostgreSQL + MCP 프로토콜, 결정적인 테스트 임베딩 (품질 평가가 아님)."""
    app = create_app(store=db_store)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8001"
        ) as http:
            for company, extension in (("seojun_roasters", "csv"), ("taegeon_beauty", "xlsx")):
                sample = DATA / company / f"corporate_values.{extension}"
                path = f"/api/v1/companies/{company}/documents/{company}-corporate_values"
                uploaded = await http.put(
                    path,
                    files={"file": (sample.name, sample.read_bytes())},
                    data={"expected_revision": "0"},
                )
                assert uploaded.status_code == 200, uploaded.text
                assert uploaded.json()["revision"] == 1
                repeated = await http.put(path, files={"file": (sample.name, sample.read_bytes())})
                assert repeated.status_code == 200
                assert repeated.json()["revision"] == 1

            extra = DATA / "seojun_roasters" / "ethics_policy.csv"
            extra_path = "/api/v1/companies/seojun_roasters/documents/seojun_roasters-ethics_policy"
            extra_upload = await http.put(
                extra_path, files={"file": (extra.name, extra.read_bytes())}
            )
            assert extra_upload.status_code == 200
            rest_query = {
                "query": "인권 존중",
                "company_id": "seojun_roasters",
                "document_ids": ["seojun_roasters-corporate_values"],
            }
            rest = await http.post("/tools/search_corporate_value", json=rest_query)
            assert rest.status_code == 200
            assert rest.json()["related_criteria"] == []
            assert rest.json()["evidence"]
            assert all(
                e["document_id"] == "seojun_roasters-corporate_values"
                for e in rest.json()["evidence"]
            )
            for invalid_ids in ([], [""], ["../bad"], ["x" * 151], ["x"] * 101):
                invalid_rest = await http.post(
                    "/tools/search_corporate_value",
                    json=rest_query | {"document_ids": invalid_ids},
                )
                assert invalid_rest.status_code == 422

            async with streamable_http_client(
                "http://localhost:8001/mcp", http_client=http
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    assert {t.name for t in listed.tools} == {
                        "search_social_context",
                        "search_corporate_value",
                    }
                    arguments = {"query": "인권 존중", "company_id": "seojun_roasters"}
                    corporate_schema = next(
                        t.inputSchema for t in listed.tools if t.name == "search_corporate_value"
                    )
                    assert "document_ids" in corporate_schema["properties"]
                    default = await session.call_tool("search_corporate_value", arguments)
                    assert not default.isError
                    assert default.structuredContent["related_criteria"] == []
                    assert SearchResult.model_validate(default.structuredContent).status == "ok"

                    for company in ("seojun_roasters", "taegeon_beauty"):
                        result = await session.call_tool(
                            "search_corporate_value",
                            arguments
                            | {
                                "company_id": company,
                                "document_ids": [f"{company}-corporate_values"],
                            },
                        )
                        assert not result.isError
                        payload = SearchResult.model_validate(result.structuredContent)
                        assert payload.status == "ok" and not payload.mock
                        assert payload.evidence
                        assert all(e.company_id == company for e in payload.evidence)
                        assert all(e.chunk_id and e.rule_id and e.version for e in payload.evidence)
                        assert all(
                            e.document_id == f"{company}-corporate_values" for e in payload.evidence
                        )

                    deleted = await http.delete(
                        "/api/v1/companies/seojun_roasters/documents/seojun_roasters-corporate_values"
                    )
                    assert deleted.status_code == 204
                    after_delete = await session.call_tool(
                        "search_corporate_value",
                        arguments | {"document_ids": ["seojun_roasters-corporate_values"]},
                    )
                    assert not after_delete.isError
                    assert (
                        SearchResult.model_validate(after_delete.structuredContent).status
                        == "empty"
                    )
                    assert (await http.get(extra_path)).status_code == 200
                    invalid = await session.call_tool(
                        "search_corporate_value", arguments | {"document_ids": []}
                    )
                    assert invalid.isError


async def test_mcp_distinguishes_storage_failure_from_empty_results():
    class UnavailableStore:
        async def search(self, *args, **kwargs):
            raise StorageUnavailable("test database unavailable")

    app = create_app(store=UnavailableStore())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8001"
        ) as http:
            rest = await http.post("/tools/search_social_context", json={"query": "인권"})
            assert rest.status_code == 503
            assert rest.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
            async with streamable_http_client(
                "http://localhost:8001/mcp", http_client=http
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    result = await session.call_tool("search_social_context", {"query": "인권"})
                    assert result.isError
