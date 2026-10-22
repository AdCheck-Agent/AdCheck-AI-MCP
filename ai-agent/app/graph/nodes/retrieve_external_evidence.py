import asyncio

import httpx
from pydantic import ValidationError

from app.clients.business_mcp_client import BusinessTools, RecentIssueResult
from app.graph.state import ReviewState


async def retrieve_external_evidence(
    state: ReviewState, tools: BusinessTools | None, timeout_seconds: float = 5
) -> dict[str, object]:
    if state["external_search_attempted"]:
        return {}
    query = state["external_search_query"]
    if not query or not query.strip() or len(query.strip()) > 400:
        return {}
    result = RecentIssueResult(
        status="unavailable",
        results=[],
        mock=False,
        message="외부검색 client가 연결되지 않았습니다.",
    )
    if tools is not None:
        try:
            async with asyncio.timeout(timeout_seconds):
                result = await tools.search_recent_issue(query.strip())
        except (TimeoutError, httpx.TimeoutException):
            result = RecentIssueResult(
                status="timeout", results=[], mock=False, message="외부검색 제한 시간 초과"
            )
        except (httpx.HTTPError, ValidationError, ValueError):
            result = RecentIssueResult(
                status="error", results=[], mock=False, message="외부검색 서비스 응답 오류"
            )
    return {
        "external_search_attempted": True,
        "external_search_result": result,
        "external_evidence": result.results if result.status == "ok" and not result.mock else [],
    }
