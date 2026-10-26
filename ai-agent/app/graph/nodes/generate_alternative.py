from app.graph.state import ReviewState
from app.llm.alternative import FAILURE_SUMMARY, attach_suggestions
from app.llm.client import get_review_model


def generate_alternative(state: ReviewState) -> dict:
    """위험한 표현마다 광고의 목적은 살린 대체 문구를 쓴다.

    믿을 만한 수정안이 없는 revise 결과는 쓸모가 없으므로, 실패하면
    (모델 오류, 빠진 항목, 금기어 재사용) 모두 needs_review로 넘긴다.
    """
    model = get_review_model()
    if model is None:
        return {
            "status": "revise",
            "summary": "[MOCK] 수정 권고 분기입니다. 수정안 생성은 미구현입니다.",
        }
    if not state["findings"]:
        return {"status": "revise", "summary": state["summary"]}

    findings = attach_suggestions(model, state)
    if findings is None:
        flagged = [f.model_copy(update={"needs_human_review": True}) for f in state["findings"]]
        return {"status": "needs_review", "summary": FAILURE_SUMMARY, "findings": flagged}
    return {"status": "revise", "summary": state["summary"], "findings": findings}
