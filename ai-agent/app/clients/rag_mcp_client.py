from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from app.schemas.review import Evidence


class RetrievalResult(BaseModel):
    evidence: list[Evidence] = Field(default_factory=list)
    mock: bool
    message: str


class RagTools(Protocol):
    async def search_social_context(self, query: str) -> RetrievalResult: ...

    async def search_corporate_value(self, query: str, company_id: str) -> RetrievalResult: ...


class RagMCPClient:
    """HTTP placeholder adapter; caller owns AsyncClient lifecycle, base URL and timeout."""

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


# TODO(AI 2): implement RagTools with real MCP transport; inject into retrieval nodes.
