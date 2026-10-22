from business_mcp.schemas import SearchResult


async def search_recent_issue(query: str) -> SearchResult:
    # TODO(AI 2, post-MVP): select search provider and preserve verified source URLs/dates.
    return SearchResult()
