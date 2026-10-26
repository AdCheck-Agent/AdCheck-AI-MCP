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


class CheckpointResult(BaseModel):
    status: Literal["ok", "timeout", "unavailable", "error"]
    http_status: int | None = None
    error_code: str | None = None
    trace_id: str | None = None
    retryable: bool = False
    message: str


class CheckpointTools(Protocol):
    async def save_checkpoint(
        self,
        original_text_id: str,
        checkpoint_level: str,
        result: dict | None = None,
        error: dict | None = None,
    ) -> CheckpointResult: ...


class BusinessTools(Protocol):
    async def search_recent_issue(self, query: str) -> RecentIssueResult: ...


class BusinessMCPClient:
    """HTTP Tool 어댑터. 실제 MCP 전송은 별도 연동 작업이다."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def search_recent_issue(self, query: str) -> RecentIssueResult:
        response = await self.http.post("/tools/search_recent_issue", json={"query": query})
        if response.status_code in (502, 503, 504):
            # 실패 상태를 타입 그대로 넘겨 Agent의 판정·오류 정책이 쓰게 한다.
            result = RecentIssueResult.model_validate(response.json())
            expected_status = {502: "error", 503: "unavailable", 504: "timeout"}
            if result.status == expected_status[response.status_code] and not result.results:
                return result
        response.raise_for_status()
        return RecentIssueResult.model_validate(response.json())


class BusinessMCPTransportClient:
    """Business 서버의 search_recent_issue Tool을 부르는 MCP (Streamable HTTP) 클라이언트.

    검색이 실패해도 structuredContent에 타입이 있는 결과가 담겨 오므로(isError는 true),
    빈 검색으로 바꾸지 않고 상태를 그대로 보존한다. 결과로 읽을 수 없는 응답은
    ValueError가 되고, 검색 노드는 이를 `error`로 보고한다.
    """

    def __init__(
        self, url: str, timeout: float = 5, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self.url, self.timeout, self.http_client = url, timeout, http_client

    async def _call_tool(self, name: str, arguments: dict):
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
                response = await session.call_tool(name, arguments)
        except TimeoutError:
            raise
        except Exception as exc:
            raise ValueError("Business MCP 호출에 실패했습니다.") from exc
        if response.structuredContent is None:
            raise ValueError("Business MCP가 구조화된 결과를 반환하지 않았습니다.")
        return response.structuredContent

    async def search_recent_issue(self, query: str) -> RecentIssueResult:
        content = await self._call_tool("search_recent_issue", {"query": query})
        return RecentIssueResult.model_validate(content)

    async def save_checkpoint(
        self,
        original_text_id: str,
        checkpoint_level: str,
        result: dict | None = None,
        error: dict | None = None,
    ) -> CheckpointResult:
        """끝난 단계를 BE에 기록하도록 Business 서버에 요청한다."""
        arguments = {"original_text_id": original_text_id, "checkpoint_level": checkpoint_level}
        if result is not None:
            arguments["result"] = result
        if error is not None:
            arguments["error"] = error
        content = await self._call_tool("save_checkpoint", arguments)
        return CheckpointResult.model_validate(content)
