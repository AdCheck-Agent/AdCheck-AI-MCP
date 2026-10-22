import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from langgraph.graph.state import CompiledStateGraph

from app.graph.state import initial_state
from app.schemas.review import ReviewRequest, ReviewResponse

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.review_graph


@router.post("/reviews", response_model=ReviewResponse)
async def review(
    payload: ReviewRequest,
    graph: Annotated[CompiledStateGraph, Depends(get_graph)],
) -> ReviewResponse:
    result = await graph.ainvoke(initial_state(payload))
    response = ReviewResponse.model_validate(result)
    logger.info("review completed trace_id=%s status=%s", response.trace_id, response.status)
    return response
