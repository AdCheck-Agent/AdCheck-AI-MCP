import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, review
from app.clients.business_mcp_client import BusinessMCPTransportClient
from app.clients.rag_mcp_client import RagMCPTransportClient
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.graph.graph import build_graph
from app.llm.client import set_review_model
from app.llm.openai_model import create_openai_model

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    model = create_openai_model(settings)
    set_review_model(model)

    rag_tools = (
        RagMCPTransportClient(
            str(settings.rag_mcp_url).rstrip("/") + "/mcp",
            settings.http_timeout_seconds,
        )
        if settings.rag_retrieval_enabled
        else None
    )

    business = BusinessMCPTransportClient(
        str(settings.business_mcp_url).rstrip("/") + "/mcp", timeout=5
    )
    application.state.checkpoint_tools = business if settings.checkpoint_enabled else None
    application.state.review_graph = build_graph(business_tools=business, rag_tools=rag_tools)

    # A missing setting does not stop the server, so say so loudly instead of reviewing quietly.
    application.state.features = {
        "review_model": "openai" if model else "mock",
        "rag_retrieval": rag_tools is not None,
        "checkpoint": settings.checkpoint_enabled,
    }
    if model is None:
        logger.warning("OPENAI_API_KEY is not set: every review returns a [MOCK] needs_review")
    if rag_tools is None:
        logger.warning("RAG_RETRIEVAL_ENABLED is false: reviews run without retrieved evidence")
    if not settings.checkpoint_enabled:
        logger.warning("CHECKPOINT_ENABLED is false: the backend never receives results")
    yield


app = FastAPI(title="AdCheck AI Agent", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(review.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=get_settings().ai_agent_port)
