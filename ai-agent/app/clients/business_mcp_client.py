from datetime import datetime
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, Field, HttpUrl


class RecentIssue(BaseModel):
    title: str
    url: HttpUrl
    snippet: str
    source: str
    score: float | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    content_check: Literal["not_checked"] = "not_checked"


class RecentIssueResult(BaseModel):
    status: Literal["ok", "empty", "timeout", "unavailable", "error"]
    results: list[RecentIssue] = Field(default_factory=list)
    related_criteria: list[str] = Field(default_factory=list)
    mock: bool
    message: str


class BusinessTools(Protocol):
    async def search_recent_issue(self, query: str) -> RecentIssueResult: ...


class BusinessMCPClient:
    """HTTP Tool adapter; real MCP transport is a separate integration task."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def search_recent_issue(self, query: str) -> RecentIssueResult:
        response = await self.http.post("/tools/search_recent_issue", json={"query": query})
        if response.status_code in (502, 503, 504):
            # Preserve a typed failure for the Agent's judgment/error policy.
            result = RecentIssueResult.model_validate(response.json())
            expected_status = {502: "error", 503: "unavailable", 504: "timeout"}
            if result.status == expected_status[response.status_code] and not result.results:
                return result
        response.raise_for_status()
        return RecentIssueResult.model_validate(response.json())


# TODO(AI 2): replace HTTP adapter with verified MCP transport when servers are migrated.
