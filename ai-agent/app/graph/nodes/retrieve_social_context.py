from app.graph.state import ReviewState


def retrieve_social_context(state: ReviewState) -> dict:
    # TODO(AI 2): await RagMCPClient.search_social_context and preserve source metadata.
    return {"social_context_evidence": []}
