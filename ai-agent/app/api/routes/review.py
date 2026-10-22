import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.graph.state import CompiledStateGraph

from app.core.config import get_settings
from app.graph.state import initial_state
from app.schemas.review import ReviewRequest, ReviewResponse

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.review_graph


def _error(status_code: int, code: str, trace_id: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "trace_id": trace_id})


@router.post("/reviews", response_model=ReviewResponse)
async def review(
    payload: ReviewRequest,
    graph: Annotated[CompiledStateGraph, Depends(get_graph)],
) -> ReviewResponse:
    """Run one review.

    needs_review is a normal answer. Only a run that cannot finish (time limit, bug) is an
    HTTP error, and it carries the trace_id so the failure can be found in the logs.
    """
    state = initial_state(payload)
    trace_id = state["trace_id"]
    logger.info("review started trace_id=%s", trace_id)
    try:
        async with asyncio.timeout(get_settings().review_timeout_seconds):
            result = await graph.ainvoke(state)
        response = ReviewResponse.model_validate(result)
    except TimeoutError:
        logger.error("review timed out trace_id=%s", trace_id)
        raise _error(504, "review_timeout", trace_id) from None
    except Exception:
        logger.exception("review failed trace_id=%s", trace_id)
        raise _error(500, "review_failed", trace_id) from None
    logger.info("review completed trace_id=%s status=%s", trace_id, response.status)
    return response
