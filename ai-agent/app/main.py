from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, review
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.graph.graph import build_graph
from app.llm.client import set_review_model
from app.llm.openai_model import create_openai_model


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    set_review_model(create_openai_model(settings))
    application.state.review_graph = build_graph()
    yield


app = FastAPI(title="AdCheck AI Agent", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(review.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=get_settings().ai_agent_port)
