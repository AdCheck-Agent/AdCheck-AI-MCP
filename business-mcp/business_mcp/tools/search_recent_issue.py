import httpx

from business_mcp.clients.tavily_client import TavilyClient
from business_mcp.config import Settings, get_settings
from business_mcp.schemas import SearchQuery, SearchResult


async def search_recent_issue(query: str, settings: Settings | None = None) -> SearchResult:
    payload = SearchQuery(query=query)
    config = settings if settings is not None else get_settings()
    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(retries=0)) as http:
        return await TavilyClient(http, config).search(payload.query)
