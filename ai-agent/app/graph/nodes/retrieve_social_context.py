import logging

from app.clients.rag_mcp_client import RagTools, RetrievalResult
from app.graph.state import ReviewState


def retrieve_social_context(state: ReviewState) -> dict:
    # 오프라인 그래프는 단위 테스트와 로컬 실행이 검색 서버 없이도 돌게 한다.
    return {"social_context_evidence": [], "social_context_result": None}


async def retrieve_social_context_live(state: ReviewState, tools: RagTools) -> dict:
    try:
        result = await tools.search_social_context(state["source_text"])
        return {"social_context_evidence": result.evidence, "social_context_result": result}
    except Exception:
        logging.getLogger(__name__).warning("RAG social failed trace_id=%s", state["trace_id"])
        return {
            "social_context_evidence": [],
            "social_context_result": RetrievalResult(
                status="error", mock=False, message="사회·역사 검색에 실패했습니다."
            ),
            "rag_errors": [*state["rag_errors"], "SOCIAL_RETRIEVAL_FAILED"],
        }
