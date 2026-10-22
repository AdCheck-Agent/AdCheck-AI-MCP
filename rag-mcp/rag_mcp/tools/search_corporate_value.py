from rag_mcp.retrieval.vector_store import MockRetriever, Retriever
from rag_mcp.schemas import SearchResult


async def search_corporate_value(
    query: str, company_id: str, retriever: Retriever | None = None
) -> SearchResult:
    store = retriever if retriever is not None else MockRetriever()
    evidence = await store.search(query, collection="corporate", company_id=company_id)
    return SearchResult(evidence=evidence)
