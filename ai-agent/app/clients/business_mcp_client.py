from typing import Protocol

import httpx
from pydantic import BaseModel, Field


class RecentIssue(BaseModel):
    title: str
    url: str
    snippet: str


class RecentIssueResult(BaseModel):
    results: list[RecentIssue] = Field(default_factory=list)
    mock: bool
    message: str


class BusinessTools(Protocol):
    async def search_recent_issue(self, query: str) -> RecentIssueResult: ...


class BusinessMCPClient:
    """HTTP placeholder adapter; external search is intentionally deferred."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def search_recent_issue(self, query: str) -> RecentIssueResult:
        response = await self.http.post("/tools/search_recent_issue", json={"query": query})
        response.raise_for_status()
        return RecentIssueResult.model_validate(response.json())


# TODO(AI 2, post-MVP): real MCP transport and optional evidence-based graph search branch.
