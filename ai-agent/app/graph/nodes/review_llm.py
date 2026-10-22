from app.graph.state import ReviewState
from app.llm.client import get_review_model
from app.llm.judge import (
    MOCK_SUMMARY,
    SYSTEM_PROMPT,
    build_catalog,
    build_user_prompt,
    call_model,
    needs_review,
    resolve,
)


def review_llm(state: ReviewState) -> dict:
    """Judge the ad text with rule hits and retrieved evidence.

    Rule hits are hints, never verdicts. The model always runs when configured; code guards
    then force needs_review when evidence is missing, so no evidence or quote is invented.
    """
    model = get_review_model()
    if model is None:
        return needs_review(MOCK_SUMMARY)

    catalog = build_catalog(state)
    judgment = call_model(model, SYSTEM_PROMPT, build_user_prompt(state, catalog))
    if judgment is None:
        return needs_review("모델 판단을 얻지 못해 사람 검토가 필요합니다.")
    return resolve(judgment, state, catalog)
