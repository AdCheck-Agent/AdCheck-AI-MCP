from app.graph.state import ReviewState
from app.llm.alternative import FAILURE_SUMMARY, attach_suggestions
from app.llm.client import get_review_model


def generate_alternative(state: ReviewState) -> dict:
    """Write a replacement for each risky quote, keeping the ad's purpose.

    A revise result without a trustworthy suggestion is not useful, so any failure
    (model error, missing item, reused banned wording) falls back to needs_review.
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
