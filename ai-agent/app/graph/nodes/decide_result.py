from app.graph.state import ReviewState


def mark_pass(state: ReviewState) -> dict:
    return {
        "status": "pass",
        "summary": "현재 근거에서 명확한 위험을 발견하지 못했습니다. 최종 확인이 필요합니다.",
    }


def mark_needs_review(state: ReviewState) -> dict:
    return {
        "status": "needs_review",
        "summary": state["summary"]
        or "근거가 부족하거나 판단이 불확실합니다. 사람 검토가 필요합니다.",
    }
