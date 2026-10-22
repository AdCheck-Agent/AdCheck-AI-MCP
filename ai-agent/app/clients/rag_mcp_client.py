from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, Field

from app.schemas.review import Evidence


class RetrievalEvidence(Evidence):
    document_id: str | None = None
    chunk_id: str | None = None
    company_id: str | None = None
    document_type: str | None = None
    record_type: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    row_id: str | None = None
    synthetic: bool = False
    score: float | None = None
    published_at: str | None = None
    category: str | None = None
    verification_status: str | None = None


class RetrievalResult(BaseModel):
    evidence: list[RetrievalEvidence] = Field(default_factory=list)
    related_criteria: list[str] = Field(default_factory=list)
    mock: bool
    message: str
    status: Literal["ok", "empty", "error"] = "empty"


class RagTools(Protocol):
    async def search_social_context(self, query: str) -> RetrievalResult: ...

    async def search_corporate_value(self, query: str, company_id: str) -> RetrievalResult: ...


class RagMCPClient:
    """HTTP alternative for diagnostics; caller owns AsyncClient lifecycle and timeout."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def search_social_context(self, query: str) -> RetrievalResult:
        response = await self.http.post("/tools/search_social_context", json={"query": query})
        response.raise_for_status()
        return RetrievalResult.model_validate(response.json())

    async def search_corporate_value(self, query: str, company_id: str) -> RetrievalResult:
        response = await self.http.post(
            "/tools/search_corporate_value", json={"query": query, "company_id": company_id}
        )
        response.raise_for_status()
        return RetrievalResult.model_validate(response.json())


class RagMCPTransportClient:
    """MCP v1 SDK client. Graph owners may inject this implementation of RagTools."""

    def __init__(self, url: str, timeout: float = 30):
        self.url, self.timeout = url, timeout

    async def call(self, name: str, arguments: dict) -> RetrievalResult:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(
                self.url, timeout=self.timeout, sse_read_timeout=self.timeout
            ) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(name, arguments)
            if result.isError:
                raise RuntimeError("RAG MCP Tool 실행에 실패했습니다.")
            return RetrievalResult.model_validate(result.structuredContent)

    async def search_social_context(self, query: str) -> RetrievalResult:
        return await self.call("search_social_context", {"query": query})

    async def search_corporate_value(self, query: str, company_id: str) -> RetrievalResult:
        return await self.call("search_corporate_value", {"query": query, "company_id": company_id})
