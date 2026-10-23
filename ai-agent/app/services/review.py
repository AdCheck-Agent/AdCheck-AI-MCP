import asyncio
import logging

from langgraph.graph.state import CompiledStateGraph

from app.checkpoint import CheckpointSink
from app.clients.business_mcp_client import CheckpointTools
from app.events import EventSink, LogSink, StageTracker, current_tracker
from app.graph.state import ReviewState
from app.schemas.review import ReviewResponse

logger = logging.getLogger(__name__)


class _Both:
    def __init__(self, *sinks: EventSink) -> None:
        self.sinks = sinks

    def emit(self, event) -> None:
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception:
                logger.exception("event sink failed")


async def run_review(
    state: ReviewState,
    graph: CompiledStateGraph,
    timeout_seconds: float,
    checkpoint_tools: CheckpointTools | None = None,
) -> ReviewResponse | None:
    """Execute after HTTP 202 and deliver the validated result in the final CP."""
    trace_id = state["trace_id"]
    review_id = state.get("review_id")
    checkpoint = (
        CheckpointSink(checkpoint_tools, review_id, trace_id, asyncio.get_running_loop())
        if checkpoint_tools and review_id
        else None
    )
    tracker = StageTracker(
        review_id, trace_id, _Both(LogSink(), checkpoint) if checkpoint else LogSink()
    )
    token = current_tracker.set(tracker)
    logger.info("review started trace_id=%s", trace_id)
    try:
        async with asyncio.timeout(timeout_seconds):
            result = await graph.ainvoke(state)
            response = ReviewResponse.model_validate(result)
        if checkpoint:
            checkpoint.complete(response)
        logger.info("review completed trace_id=%s status=%s", trace_id, response.status)
        return response
    except TimeoutError:
        tracker.fail_running()
        logger.error("review timed out trace_id=%s code=review_timeout", trace_id)
        return None
    except Exception:
        tracker.fail_running()
        logger.exception("review failed trace_id=%s code=review_failed", trace_id)
        return None
    finally:
        current_tracker.reset(token)
        if checkpoint:
            await checkpoint.close(timeout=30)
