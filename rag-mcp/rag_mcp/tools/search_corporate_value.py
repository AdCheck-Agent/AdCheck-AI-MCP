from rag_mcp.retrieval.vector_store import Retriever
from rag_mcp.schemas import SearchResult


async def search_corporate_value(
    query: str,
    company_id: str,
    retriever: Retriever,
    top_k: int = 5,
    min_score: float = 0.0,
    include_synthetic: bool = False,
) -> SearchResult:
    evidence = await retriever.search(
        query,
        collection="corporate",
        company_id=company_id,
        top_k=top_k,
        min_score=min_score,
        include_synthetic=include_synthetic,
    )
    return SearchResult(evidence=evidence, status="ok" if evidence else "empty")
