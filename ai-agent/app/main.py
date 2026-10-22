from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.routes import health, review
from app.clients.business_mcp_client import BusinessMCPClient
from app.clients.rag_mcp_client import RagMCPTransportClient
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.graph.graph import build_graph


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    rag_tools = (
        RagMCPTransportClient(
            str(settings.rag_mcp_url).rstrip("/") + "/mcp",
            settings.http_timeout_seconds,
        )
        if settings.rag_retrieval_enabled
        else None
    )

    async with httpx.AsyncClient(
        base_url=str(settings.business_mcp_url),
        timeout=5,
        transport=httpx.AsyncHTTPTransport(retries=0),
    ) as http:
        application.state.review_graph = build_graph(
            business_tools=BusinessMCPClient(http),
            rag_tools=rag_tools,
        )
        yield


app = FastAPI(title="AdCheck AI Agent", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(review.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=get_settings().ai_agent_port)