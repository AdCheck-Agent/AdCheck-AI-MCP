from typing import Protocol

from rag_mcp.schemas import RetrievedEvidence


class Retriever(Protocol):
    async def search(
        self, query: str, *, collection: str, company_id: str | None = None
    ) -> list[RetrievedEvidence]: ...


class MockRetriever:
    async def search(
        self, query: str, *, collection: str, company_id: str | None = None
    ) -> list[RetrievedEvidence]:
        # TODO(AI 2): Qdrant adapter using QDRANT_URL, collection and company_id metadata filter.
        return []
