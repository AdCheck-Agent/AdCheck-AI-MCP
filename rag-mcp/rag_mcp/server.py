from fastapi import FastAPI

from rag_mcp.schemas import CorporateQuery, SearchQuery, SearchResult
from rag_mcp.tools.search_corporate_value import search_corporate_value
from rag_mcp.tools.search_social_context import search_social_context

# HTTP placeholder only. TODO(AI 2): register tools with a verified MCP SDK transport.
app = FastAPI(title="AdCheck RAG MCP HTTP placeholder", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "adcheck-rag-mcp", "mode": "http-placeholder"}


@app.post("/tools/search_social_context", response_model=SearchResult)
async def social(payload: SearchQuery) -> SearchResult:
    return await search_social_context(payload.query)


@app.post("/tools/search_corporate_value", response_model=SearchResult)
async def corporate(payload: CorporateQuery) -> SearchResult:
    return await search_corporate_value(payload.query, payload.company_id)
