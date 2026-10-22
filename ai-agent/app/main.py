from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, review
from app.clients.rag_mcp_client import RagMCPTransportClient
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.graph.graph import build_graph


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    settings = get_settings()
    rag_tools = (
        RagMCPTransportClient(
            str(settings.rag_mcp_url).rstrip("/") + "/mcp", settings.http_timeout_seconds
        )
        if settings.rag_retrieval_enabled
        else None
    )
    application.state.review_graph = build_graph(rag_tools=rag_tools)
    yield


app = FastAPI(title="AdCheck AI Agent", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(review.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=get_settings().ai_agent_port)
