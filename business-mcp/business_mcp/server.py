from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from business_mcp.config import Settings, get_settings
from business_mcp.schemas import SearchQuery, SearchResult
from business_mcp.tools.search_recent_issue import search_recent_issue

# HTTP placeholder only. TODO(AI 2): use a verified MCP SDK when transport is selected.
app = FastAPI(title="AdCheck Business Search HTTP Tool", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "adcheck-business-mcp", "mode": "http-tool"}


@app.post(
    "/tools/search_recent_issue",
    response_model=SearchResult,
    responses={code: {"model": SearchResult} for code in (502, 503, 504)},
)
async def recent_issue(
    payload: SearchQuery, settings: Annotated[Settings, Depends(get_settings)]
) -> SearchResult | JSONResponse:
    result = await search_recent_issue(payload.query, settings)
    error_status = {"error": 502, "unavailable": 503, "timeout": 504}.get(result.status)
    if error_status is not None:
        return JSONResponse(status_code=error_status, content=result.model_dump(mode="json"))
    return result
