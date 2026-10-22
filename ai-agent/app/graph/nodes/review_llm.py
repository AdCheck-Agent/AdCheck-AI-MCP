from app.graph.state import ReviewState


def review_llm(state: ReviewState) -> dict:
    # TODO(AI 1): structured LLM context judgment, evidence sufficiency and conflict detection.
    # A rule match alone does not establish a violation; no invented evidence in mock mode.
    # TODO(AI 1): set external_search_query ONLY for a public fact that web search can resolve.
    # After the one external search, reassess external_evidence without treating hits as proof.
    return {
        "evidence_sufficient": False,
        "risk": "uncertain",
        "findings": [],
        "summary": (
            "[MOCK] LLM 판정은 아직 구현하지 않았습니다. 검색 여부와 별개로 사람 검토가 필요합니다."
        ),
    }
