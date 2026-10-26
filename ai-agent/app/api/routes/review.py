import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from langgraph.graph.state import CompiledStateGraph

from app.core.config import get_settings
from app.graph.state import initial_state
from app.schemas.review import ReviewAccepted, ReviewRequest
from app.services.review import run_review

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.review_graph


@router.post("/reviews", status_code=202, response_model=ReviewAccepted)
async def review(
    payload: ReviewRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    graph: Annotated[CompiledStateGraph, Depends(get_graph)],
) -> ReviewAccepted:
    """요청을 접수하고, HTTP 202를 보낸 뒤 검수를 실행한다."""
    state = initial_state(payload)
    trace_id = state["trace_id"]
    background_tasks.add_task(
        run_review,
        state,
        graph,
        get_settings().review_timeout_seconds,
        getattr(request.app.state, "checkpoint_tools", None),
    )
    logger.info("review accepted trace_id=%s", trace_id)
    return ReviewAccepted(trace_id=trace_id)
