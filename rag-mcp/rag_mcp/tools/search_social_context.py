from rag_mcp.retrieval.vector_store import Retriever
from rag_mcp.schemas import SearchResult


async def search_social_context(
    query: str, retriever: Retriever, top_k: int = 5, min_score: float = 0.0
) -> SearchResult:
    evidence = await retriever.search(query, collection="social", top_k=top_k, min_score=min_score)
    return SearchResult(evidence=evidence, status="ok" if evidence else "empty")
