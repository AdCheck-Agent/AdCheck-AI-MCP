import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from pydantic import BaseModel, Field, HttpUrl, ValidationError

from business_mcp.config import Settings
from business_mcp.schemas import RecentIssue, SearchResult


class TavilyItem(BaseModel):
    title: str
    url: HttpUrl
    content: str
    score: float | None = Field(default=None, ge=0, le=1)
    published_date: str | None = None


class TavilyResponse(BaseModel):
    results: list[TavilyItem]


def parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    # 출처가 날짜나 현지 시각만 주면 시간대를 지어내지 않는다.
    return parsed if parsed.tzinfo is not None else None


class TavilyClient:
    """Search HTTP 호출 한 번. 재시도, 리다이렉트, Extract, 생성 답변은 쓰지 않는다."""

    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self.http = http
        self.settings = settings

    async def search(self, query: str) -> SearchResult:
        key = self.settings.tavily_api_key
        if key is None or not key.get_secret_value().strip():
            return SearchResult(
                status="unavailable", message="TAVILY_API_KEY가 설정되지 않았습니다."
            )
        try:
            # httpx의 단계별 시간 제한과 달리, 요청 전체 시간을 제한한다.
            async with asyncio.timeout(self.settings.tavily_timeout_seconds):
                response = await self.http.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                    json={
                        "query": query,
                        "max_results": self.settings.tavily_max_results,
                        "search_depth": "basic",
                        "auto_parameters": False,
                        "include_answer": False,
                        "include_raw_content": False,
                        "include_published_date": True,
                    },
                    timeout=self.settings.tavily_timeout_seconds,
                    follow_redirects=False,
                )
                response.raise_for_status()
                payload = TavilyResponse.model_validate(response.json())
        except (TimeoutError, httpx.TimeoutException):
            return SearchResult(status="timeout", message="외부검색 제한 시간을 초과했습니다.")
        except (httpx.HTTPError, ValidationError, ValueError):
            # 제공사 응답 본문, 요청 헤더, 인증 정보는 절대 노출하지 않는다.
            return SearchResult(
                status="error", message="외부검색 호출 또는 응답 처리에 실패했습니다."
            )

        results: list[RecentIssue] = []
        seen: set[str] = set()
        retrieved_at = datetime.now(UTC)
        for item in payload.results:
            url = str(item.url)
            if url in seen or not item.title.strip() or not item.content.strip():
                continue
            seen.add(url)
            results.append(
                RecentIssue(
                    title=item.title.strip(),
                    url=item.url,
                    snippet=item.content.strip(),
                    source=item.url.host or "",
                    score=item.score,
                    published_at=parse_published_at(item.published_date),
                    retrieved_at=retrieved_at,
                )
            )
            if len(results) >= self.settings.tavily_max_results:
                break
        return SearchResult(
            status="ok" if results else "empty",
            results=results,
            message="검색 결과입니다. 원문 별도 확인 및 사실 검증은 수행하지 않았습니다."
            if results
            else "사용 가능한 검색 결과가 없습니다.",
        )
