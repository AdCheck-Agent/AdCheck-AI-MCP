from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from pydantic import StringConstraints

from business_mcp.config import Settings, get_settings
from business_mcp.schemas import SearchQuery, SearchResult
from business_mcp.tools.search_recent_issue import search_recent_issue


def create_app(settings: Settings | None = None) -> FastAPI:
    mcp = FastMCP(
        "adcheck-business-mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["localhost:*", "127.0.0.1:*", "business-mcp:*", "testserver"],
        ),
    )
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="AdCheck Business MCP", version="0.2.0", lifespan=lifespan)
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "adcheck-business-mcp", "mode": "mcp-http"}

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

    @mcp.tool(name="search_recent_issue")
    async def recent_issue_tool(
        query: Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)
        ],
    ) -> Annotated[CallToolResult, SearchResult]:
        """Search public web evidence. Results are unverified; inspect status before use."""
        result = await search_recent_issue(
            query, settings if settings is not None else get_settings()
        )
        return CallToolResult(
            content=[TextContent(type="text", text=result.model_dump_json())],
            structuredContent=result.model_dump(mode="json"),
            isError=result.status in {"error", "unavailable", "timeout"},
        )

    app.mount("/", mcp_app)
    return app


app = create_app()
