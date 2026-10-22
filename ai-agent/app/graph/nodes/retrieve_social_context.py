import logging

from app.clients.rag_mcp_client import RagTools
from app.graph.state import ReviewState


def retrieve_social_context(state: ReviewState) -> dict:
    # Offline graph keeps unit tests and local startup independent of the search server.
    return {"social_context_evidence": []}


async def retrieve_social_context_live(state: ReviewState, tools: RagTools) -> dict:
    try:
        result = await tools.search_social_context(state["source_text"])
        return {"social_context_evidence": result.evidence}
    except Exception:
        logging.getLogger(__name__).warning("RAG social failed trace_id=%s", state["trace_id"])
        return {
            "social_context_evidence": [],
            "rag_errors": [*state["rag_errors"], "SOCIAL_RETRIEVAL_FAILED"],
        }
