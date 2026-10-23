import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.graph.state import CompiledStateGraph

from app.checkpoint import CheckpointSink
from app.core.config import get_settings
from app.events import EventSink, LogSink, StageTracker, current_tracker
from app.graph.state import initial_state
from app.schemas.review import ReviewRequest, ReviewResponse

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


def _error(status_code: int, code: str, trace_id: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "trace_id": trace_id})


@router.post("/reviews", response_model=ReviewResponse)
async def review(
    payload: ReviewRequest,
    request: Request,
    graph: Annotated[CompiledStateGraph, Depends(get_graph)],
) -> ReviewResponse:
    """Run one review.

    needs_review is a normal answer. Only a run that cannot finish (time limit, bug) is an
    HTTP error, and it carries the trace_id so the failure can be found in the logs.
    """
    state = initial_state(payload)
    trace_id = state["trace_id"]
    logger.info("review started trace_id=%s", trace_id)
    checkpoints: CheckpointSink | None = None
    sink: EventSink = LogSink()
    checkpoint_tools = getattr(request.app.state, "checkpoint_tools", None)
    if checkpoint_tools is not None:
        checkpoints = CheckpointSink(
            checkpoint_tools, state["review_id"], trace_id, asyncio.get_running_loop()
        )
        sink = _Both(LogSink(), checkpoints)
    tracker = StageTracker(state["review_id"], trace_id, sink)
    current_tracker.set(tracker)
    response: ReviewResponse | None = None
    try:
        async with asyncio.timeout(get_settings().review_timeout_seconds):
            result = await graph.ainvoke(state)
        response = ReviewResponse.model_validate(result)
    except TimeoutError:
        tracker.fail_running()
        logger.error("review timed out trace_id=%s", trace_id)
        raise _error(504, "review_timeout", trace_id) from None
    except Exception:
        tracker.fail_running()
        logger.exception("review failed trace_id=%s", trace_id)
        raise _error(500, "review_failed", trace_id) from None
    finally:
        # Stage checkpoints go out first; COMPLETED is added only after a finished review.
        if checkpoints is not None:
            if response is not None:
                checkpoints.complete()
            await checkpoints.close()
    logger.info("review completed trace_id=%s status=%s", trace_id, response.status)
    return response
