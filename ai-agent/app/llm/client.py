from typing import Protocol


class ReviewModel(Protocol):
    """특정 제공사에 묶이지 않는 텍스트 모델. 구현체가 시간 제한을 관리하고 실패하면 예외를 낸다."""

    def generate(self, system: str, user: str) -> str: ...


_model: ReviewModel | None = None


def set_review_model(model: ReviewModel | None) -> None:
    global _model
    _model = model


def get_review_model() -> ReviewModel | None:
    return _model
