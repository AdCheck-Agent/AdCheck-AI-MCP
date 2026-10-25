from app.graph.state import ReviewState
from app.llm.client import get_review_model
from app.llm.judge import (
    MOCK_SUMMARY,
    SYSTEM_PROMPT,
    build_catalog,
    build_user_prompt,
    call_model,
    external_query,
    needs_review,
    note_oversized,
    quote_retry_hint,
    quotes_not_in_ad,
    resolve,
)


def review_llm(state: ReviewState) -> dict:
    """Judge the ad text with rule hits and retrieved evidence.

    Rule hits are hints, never verdicts. The model always runs when configured; code guards
    then force needs_review when evidence is missing, so no evidence or quote is invented.
    When evidence is still short, the model may ask for one external search; the graph runs it
    and calls this node again with the result.
    """
    model = get_review_model()
    if model is None:
        return needs_review(MOCK_SUMMARY)

    if any(code.endswith("_FAILED") for code in state["rag_errors"]):
        # A broken search service is not "no evidence"; do not spend a model call guessing.
        return needs_review("검색 서비스 오류로 근거를 확인하지 못해 사람 검토가 필요합니다.")

    catalog = build_catalog(state)
    judgment = call_model(model, SYSTEM_PROMPT, build_user_prompt(state, catalog))
    if judgment is None:
        return needs_review("모델 판단을 얻지 못해 사람 검토가 필요합니다.")
    misquoted = quotes_not_in_ad(judgment, state)
    if misquoted:
        # A quote the ad never says is dropped below, leaving "risky" with nothing to point at.
        # Ask once more; if the answer is no better, the guards still send it to a person.
        prompt = build_user_prompt(state, catalog) + quote_retry_hint(misquoted)
        judgment = call_model(model, SYSTEM_PROMPT, prompt) or judgment

    result = note_oversized(resolve(judgment, state, catalog), state)
    query = external_query(judgment, state, result)
    if query:
        result["external_search_query"] = query
    return result
