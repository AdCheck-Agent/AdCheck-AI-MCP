from app.graph.state import ReviewState
from app.schemas.review import ReviewResponse


def validate_result(state: ReviewState) -> dict:
    ReviewResponse.model_validate(state)
    # TODO(AI 1): verify evidence against retrieved sources and quote spans before publishing.
    return {}
