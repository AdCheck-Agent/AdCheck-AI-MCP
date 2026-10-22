from typing import Protocol


class ReviewModel(Protocol):
    """Provider-agnostic text model. Implementations own timeouts and raise on failure."""

    def generate(self, system: str, user: str) -> str: ...


_model: ReviewModel | None = None


def set_review_model(model: ReviewModel | None) -> None:
    global _model
    _model = model


def get_review_model() -> ReviewModel | None:
    return _model
