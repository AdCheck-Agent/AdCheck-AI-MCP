import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from langgraph.graph.state import CompiledStateGraph

from app.checkpoint import CheckpointSink
from app.core.config import get_settings
from app.events import EventSink, LogSink, StageTracker, current_tracker
from app.graph.state import initial_state
from app.schemas.review import ReviewAccepted, ReviewRequest
from app.services.review import run_review

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


class _Both:
    """Send each event to every sink; one failing sink must not hide it from the other."""

    def __init__(self, *sinks: EventSink) -> None:
        self.sinks = sinks

    def emit(self, event) -> None:
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception:
                logger.exception("event sink failed")


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.review_graph


@router.post("/reviews", status_code=202, response_model=ReviewAccepted)
async def review(
    payload: ReviewRequest,
    background_tasks: BackgroundTasks,
    graph: Annotated[CompiledStateGraph, Depends(get_graph)],
) -> ReviewAccepted:
    """Acknowledge the request, then execute the review after sending HTTP 202."""
    state = initial_state(payload)
    trace_id = state["trace_id"]
    background_tasks.add_task(run_review, state, graph, get_settings().review_timeout_seconds)
    logger.info("review accepted trace_id=%s", trace_id)
    return ReviewAccepted(trace_id=trace_id)
