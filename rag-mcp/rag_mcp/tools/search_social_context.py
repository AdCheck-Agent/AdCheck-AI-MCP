from rag_mcp.retrieval.vector_store import MockRetriever, Retriever
from rag_mcp.schemas import SearchResult


async def search_social_context(query: str, retriever: Retriever | None = None) -> SearchResult:
    store = retriever if retriever is not None else MockRetriever()
    evidence = await store.search(query, collection="social")
    return SearchResult(evidence=evidence)
