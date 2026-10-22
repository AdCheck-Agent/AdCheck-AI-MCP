from contextlib import AsyncExitStack
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


class BusinessMCPTransportClient:
    """MCP (Streamable HTTP) client for the Business server's search_recent_issue Tool.

    A failed search still carries a typed result in structuredContent (isError is true), so
    the status is preserved instead of being turned into an empty search. Anything that
    cannot be read as a result becomes ValueError, which the search node reports as `error`.
    """

    def __init__(
        self, url: str, timeout: float = 5, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self.url, self.timeout, self.http_client = url, timeout, http_client

    async def search_recent_issue(self, query: str) -> RecentIssueResult:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        try:
            async with AsyncExitStack() as stack:
                http = self.http_client or await stack.enter_async_context(
                    httpx.AsyncClient(timeout=self.timeout)
                )
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(self.url, http_client=http)
                )
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                response = await session.call_tool("search_recent_issue", {"query": query})
        except TimeoutError:
            raise
        except Exception as exc:
            raise ValueError("Business MCP 호출에 실패했습니다.") from exc
        if response.structuredContent is None:
            raise ValueError("Business MCP가 구조화된 결과를 반환하지 않았습니다.")
        return RecentIssueResult.model_validate(response.structuredContent)
