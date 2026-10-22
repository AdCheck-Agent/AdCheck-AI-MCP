import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, File, Form, Response, UploadFile
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from rag_mcp.config import Settings
from rag_mcp.documents import corporate_document, parse_policies
from rag_mcp.errors import DocumentError, EmbeddingUnavailable, StorageUnavailable
from rag_mcp.retrieval.embeddings import LocalEmbeddings
from rag_mcp.retrieval.vector_store import PgVectorStore
from rag_mcp.schemas import CorporateQuery, DocumentResult, SearchQuery, SearchResult
from rag_mcp.tools.search_corporate_value import search_corporate_value
from rag_mcp.tools.search_social_context import search_social_context


def create_app(store: PgVectorStore | None = None, settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    backend = store or PgVectorStore(config, LocalEmbeddings(config))
    mcp = FastMCP(
        "adcheck-rag-mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["localhost:*", "127.0.0.1:*", "rag-mcp:*", "testserver"],
        ),
    )
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="AdCheck RAG MCP / pgvector", version="0.2.0", lifespan=lifespan)
    app.state.store = backend

    @app.exception_handler(DocumentError)
    async def document_error(request, exc: DocumentError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": str(exc), "retryable": False}},
        )

    @app.exception_handler(StorageUnavailable)
    async def storage_error(request, exc: StorageUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"code": "STORAGE_UNAVAILABLE", "message": str(exc), "retryable": True}
            },
        )

    @app.exception_handler(EmbeddingUnavailable)
    async def embedding_error(request, exc: EmbeddingUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"code": "EMBEDDING_UNAVAILABLE", "message": str(exc), "retryable": True}
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "adcheck-rag-mcp", "mode": "pgvector-mcp"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        await backend.ready()
        return {"status": "ok", "storage": "pgvector"}

    @app.post("/tools/search_social_context", response_model=SearchResult)
    async def social(payload: SearchQuery) -> SearchResult:
        return await search_social_context(payload.query, backend, payload.top_k, payload.min_score)

    @app.post("/tools/search_corporate_value", response_model=SearchResult)
    async def corporate(payload: CorporateQuery) -> SearchResult:
        return await search_corporate_value(
            payload.query,
            payload.company_id,
            backend,
            payload.top_k,
            payload.min_score,
            payload.include_synthetic,
            payload.document_ids,
        )

    @mcp.tool(name="search_social_context")
    async def social_tool(query: str, top_k: int = 5, min_score: float = 0.0) -> SearchResult:
        """Search repository social/history evidence. Scores are cosine similarity, not truth."""
        return await social(SearchQuery(query=query, top_k=top_k, min_score=min_score))

    @mcp.tool(name="search_corporate_value")
    async def corporate_tool(
        query: str,
        company_id: str,
        top_k: int = 5,
        min_score: float = 0.0,
        include_synthetic: bool = False,
        document_ids: list[str] | None = None,
    ) -> SearchResult:
        """For attached files, pass their document_ids. Demo files need include_synthetic=true."""
        return await corporate(
            CorporateQuery(
                query=query,
                company_id=company_id,
                top_k=top_k,
                min_score=min_score,
                include_synthetic=include_synthetic,
                document_ids=document_ids,
            )
        )

    path = "/api/v1/companies/{company_id}/documents/{document_id}"

    @app.put(path, response_model=DocumentResult)
    async def upload(
        company_id: str,
        document_id: str,
        file: Annotated[UploadFile, File()],
        expected_revision: Annotated[int | None, Form(ge=0)] = None,
    ) -> DocumentResult:
        try:
            data = await file.read(config.rag_max_upload_bytes + 1)
            rows = await asyncio.to_thread(parse_policies, file.filename or "", data, config)
        finally:
            await file.close()
        if rows[0].company_id != company_id or rows[0].document_id != document_id:
            raise DocumentError("파일의 기업·문서 ID가 URL과 다릅니다.", "IDENTITY_MISMATCH")
        document = await corporate_document(rows, backend.embeddings)
        return await backend.replace(document, expected_revision)

    @app.get(path, response_model=DocumentResult)
    async def get_document(company_id: str, document_id: str) -> DocumentResult:
        return await backend.get(company_id, document_id)

    @app.delete(path, status_code=204)
    async def delete_document(company_id: str, document_id: str) -> Response:
        await backend.delete(company_id, document_id)
        return Response(status_code=204)

    app.mount("/", mcp_app)
    return app


app = create_app()
