import asyncio
import logging

from langgraph.graph.state import CompiledStateGraph

from app.graph.state import ReviewState
from app.schemas.review import ReviewResponse

logger = logging.getLogger(__name__)


async def run_review(
    state: ReviewState, graph: CompiledStateGraph, timeout_seconds: float
) -> ReviewResponse | None:
    """Execute after the acceptance response. Result delivery is integrated separately.

    BackgroundTasks ignores this return value; it is not a second HTTP response.
    The separate SSE implementation can publish the validated response here.
    """
    trace_id = state["trace_id"]
    logger.info("review started trace_id=%s", trace_id)
    try:
        async with asyncio.timeout(timeout_seconds):
            result = await graph.ainvoke(state)
            response = ReviewResponse.model_validate(result)
    except TimeoutError:
        logger.error("review timed out trace_id=%s code=review_timeout", trace_id)
        return None
    except Exception:
        logger.exception("review failed trace_id=%s code=review_failed", trace_id)
        return None
    logger.info("review completed trace_id=%s status=%s", trace_id, response.status)
    return response
