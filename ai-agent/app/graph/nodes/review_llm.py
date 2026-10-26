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
    """금기어 탐지 결과와 검색된 근거로 광고 문구를 판정한다.

    금기어는 힌트일 뿐 판정이 아니다. 모델이 설정돼 있으면 항상 실행하고, 근거가 없으면
    코드 안전장치가 needs_review로 바꾸므로 근거나 인용을 지어내지 않는다.
    근거가 여전히 부족하면 모델이 외부 검색을 한 번 요청할 수 있고, 그래프가 검색한 뒤
    그 결과로 이 노드를 다시 부른다.
    """
    model = get_review_model()
    if model is None:
        return needs_review(MOCK_SUMMARY)

    if any(code.endswith("_FAILED") for code in state["rag_errors"]):
        # 검색 서비스 고장은 "근거 없음"이 아니다. 추측하느라 모델을 호출하지 않는다.
        return needs_review("검색 서비스 오류로 근거를 확인하지 못해 사람 검토가 필요합니다.")

    catalog = build_catalog(state)
    judgment = call_model(model, SYSTEM_PROMPT, build_user_prompt(state, catalog))
    if judgment is None:
        return needs_review("모델 판단을 얻지 못해 사람 검토가 필요합니다.")
    misquoted = quotes_not_in_ad(judgment, state)
    if misquoted:
        # 광고에 없는 인용은 아래에서 버려지므로, "위험"인데 가리킬 표현이 없어진다.
        # 한 번 더 묻고, 그래도 나아지지 않으면 안전장치가 사람 검토로 보낸다.
        prompt = build_user_prompt(state, catalog) + quote_retry_hint(misquoted)
        judgment = call_model(model, SYSTEM_PROMPT, prompt) or judgment

    result = note_oversized(resolve(judgment, state, catalog), state)
    query = external_query(judgment, state, result)
    if query:
        result["external_search_query"] = query
    return result
