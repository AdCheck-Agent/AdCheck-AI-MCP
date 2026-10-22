from app.graph.state import ReviewState


def generate_alternative(state: ReviewState) -> dict:
    # TODO(AI 1): generate grounded alternatives preserving intent; validate quotes and evidence.
    return {
        "status": "revise",
        "summary": "[MOCK] 수정 권고 분기입니다. 수정안 생성은 미구현입니다.",
    }
