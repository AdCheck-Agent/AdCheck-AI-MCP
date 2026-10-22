import logging

from app.clients.rag_mcp_client import RagTools, RetrievalResult
from app.graph.state import ReviewState


def retrieve_corporate_value(state: ReviewState) -> dict:
    return {"corporate_value_evidence": [], "corporate_value_result": None}


async def retrieve_corporate_value_live(state: ReviewState, tools: RagTools) -> dict:
    company_id = state["context"].company_id
    if not company_id:
        return {
            "corporate_value_evidence": [],
            "corporate_value_result": None,
            "rag_errors": [*state["rag_errors"], "COMPANY_NOT_SPECIFIED"],
        }
    try:
        result = await tools.search_corporate_value(
            state["source_text"], company_id, document_ids=state["context"].document_ids
        )
        return {"corporate_value_evidence": result.evidence, "corporate_value_result": result}
    except Exception:
        logging.getLogger(__name__).warning("RAG corporate failed trace_id=%s", state["trace_id"])
        return {
            "corporate_value_evidence": [],
            "corporate_value_result": RetrievalResult(
                status="error", mock=False, message="기업 문서 검색에 실패했습니다."
            ),
            "rag_errors": [*state["rag_errors"], "CORPORATE_RETRIEVAL_FAILED"],
        }
