from fastapi import FastAPI

from business_mcp.schemas import SearchQuery, SearchResult
from business_mcp.tools.search_recent_issue import search_recent_issue

# HTTP placeholder only. TODO(AI 2): use a verified MCP SDK when transport is selected.
app = FastAPI(title="AdCheck Business MCP HTTP placeholder", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "adcheck-business-mcp", "mode": "http-placeholder"}


@app.post("/tools/search_recent_issue", response_model=SearchResult)
async def recent_issue(payload: SearchQuery) -> SearchResult:
    return await search_recent_issue(payload.query)
