import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from rag_mcp.config import Settings
from rag_mcp.errors import AttachedDocumentsTooLarge, DocumentError, StorageUnavailable
from rag_mcp.retrieval.embeddings import Embeddings
from rag_mcp.schemas import DocumentRecord, DocumentResult, RetrievedEvidence


class Retriever(Protocol):
    async def search(
        self,
        query: str,
        *,
        collection: str,
        company_id: str | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
        document_ids: list[str] | None = None,
    ) -> list[RetrievedEvidence]: ...


def _scope(company_id: str | None) -> str:
    return f"company:{company_id}" if company_id is not None else "social"


def _result(row: dict, count: int) -> DocumentResult:
    return DocumentResult(
        **{
            k: row[k]
            for k in (
                "company_id",
                "document_id",
                "document_type",
                "title",
                "version",
                "revision",
            )
        },
        chunk_count=count,
    )


class PgVectorStore:
    def __init__(self, settings: Settings, embeddings: Embeddings):
        self.settings, self.embeddings = settings, embeddings

    @asynccontextmanager
    async def connection(self, *, check_profile: bool = True) -> AsyncIterator:
        try:
            async with await psycopg.AsyncConnection.connect(
                self.settings.rag_database_url, row_factory=dict_row, connect_timeout=5
            ) as conn:
                await conn.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self.settings.rag_statement_timeout_ms),),
                )
                if check_profile:
                    cursor = await conn.execute("SELECT embedding_profile FROM adcheck_rag.profile")
                    row = await cursor.fetchone()
                    if not row or row["embedding_profile"] != self.embeddings.profile:
                        raise StorageUnavailable(
                            "DB 임베딩 모델이 다릅니다. 별도 DB에 재적재하세요."
                        )
                yield conn
        except psycopg.Error as exc:
            raise StorageUnavailable("pgvector DB 또는 schema를 확인하세요.") from exc

    async def initialize(self) -> None:
        async with self.connection(check_profile=False) as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(781532)")
            schema = Path(__file__).resolve().parents[1].joinpath("schema.sql").read_text()
            await conn.execute(schema.replace("vector(384)", f"vector({self.embeddings.dim})"))
            await conn.execute(
                "INSERT INTO adcheck_rag.profile(embedding_profile) VALUES (%s) "
                "ON CONFLICT DO NOTHING",
                (self.embeddings.profile,),
            )
        await self.ready()

    async def ready(self) -> None:
        async with self.connection() as conn:
            await conn.execute("SELECT 1 FROM adcheck_rag.chunks LIMIT 1")

    async def replace(
        self, document: DocumentRecord, expected_revision: int | None = None
    ) -> DocumentResult:
        if not document.chunks:
            raise DocumentError("적재할 본문 chunk가 없습니다.")
        vectors = await self.embeddings.embed([c.content for c in document.chunks])
        scope = _scope(document.company_id)
        checksum = hashlib.sha256(
            (
                self.embeddings.profile
                + json.dumps(document.model_dump(mode="json"), sort_keys=True)
            ).encode()
        ).hexdigest()
        async with self.connection() as conn:
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (json.dumps([scope, document.document_id]),),
            )
            cur = await conn.execute(
                "SELECT * FROM adcheck_rag.documents WHERE scope=%s AND document_id=%s",
                (scope, document.document_id),
            )
            previous = await cur.fetchone()
            revision = previous["revision"] if previous else 0
            if expected_revision is not None and expected_revision != revision:
                raise DocumentError("문서 revision이 변경됐습니다.", "REVISION_CONFLICT", 409)
            if previous and previous["checksum"] == checksum:
                cur = await conn.execute(
                    "SELECT count(*) AS n FROM adcheck_rag.chunks "
                    "WHERE scope=%s AND document_id=%s",
                    (scope, document.document_id),
                )
                return _result(previous, (await cur.fetchone())["n"])
            cur = await conn.execute(
                "INSERT INTO adcheck_rag.documents "
                "(scope,document_id,company_id,corpus,document_type,title,version,"
                "checksum,revision,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(scope,document_id) DO UPDATE SET "
                "document_type=EXCLUDED.document_type,title=EXCLUDED.title,version=EXCLUDED.version,"
                "checksum=EXCLUDED.checksum,revision=EXCLUDED.revision,"
                "metadata=EXCLUDED.metadata,updated_at=now() RETURNING *",
                (
                    scope,
                    document.document_id,
                    document.company_id,
                    document.corpus,
                    document.document_type,
                    document.title,
                    # 작성자가 아니라 여기서 매긴다. 같은 내용 재업로드는 유지, 바뀌면 올린다.
                    f"v{revision + 1}",
                    checksum,
                    revision + 1,
                    Jsonb(document.metadata),
                ),
            )
            saved = await cur.fetchone()
            await conn.execute(
                "DELETE FROM adcheck_rag.chunks WHERE scope=%s AND document_id=%s",
                (scope, document.document_id),
            )
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO adcheck_rag.chunks "
                    "(scope,document_id,chunk_id,section,content,metadata,embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s::vector)",
                    [
                        (
                            scope,
                            document.document_id,
                            c.chunk_id,
                            c.section,
                            c.content,
                            Jsonb(c.metadata),
                            str(v),
                        )
                        for c, v in zip(document.chunks, vectors, strict=True)
                    ],
                )
            return _result(saved, len(document.chunks))

    async def get(self, company_id: str, document_id: str) -> DocumentResult:
        async with self.connection() as conn:
            cur = await conn.execute(
                "SELECT d.*,count(c.chunk_id) AS chunk_count FROM adcheck_rag.documents d "
                "LEFT JOIN adcheck_rag.chunks c USING(scope,document_id) "
                "WHERE d.scope=%s AND d.document_id=%s GROUP BY d.scope,d.document_id",
                (_scope(company_id), document_id),
            )
            row = await cur.fetchone()
            if not row:
                raise DocumentError("문서를 찾을 수 없습니다.", "DOCUMENT_NOT_FOUND", 404)
            return _result(row, row["chunk_count"])

    async def delete(self, company_id: str, document_id: str) -> None:
        async with self.connection() as conn:
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (json.dumps([_scope(company_id), document_id]),),
            )
            cur = await conn.execute(
                "DELETE FROM adcheck_rag.documents WHERE scope=%s AND document_id=%s RETURNING 1",
                (_scope(company_id), document_id),
            )
            if not await cur.fetchone():
                raise DocumentError("문서를 찾을 수 없습니다.", "DOCUMENT_NOT_FOUND", 404)

    async def search(
        self,
        query: str,
        *,
        collection: str,
        company_id: str | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
        document_ids: list[str] | None = None,
    ) -> list[RetrievedEvidence]:
        """유사도로 순위를 매기거나, document_ids가 있으면 첨부 파일의 조각을 모두 돌려준다.

        첨부 파일은 호출하는 쪽이 고른 범위이므로 top_k/min_score를 적용하지 않는다.
        조각은 파일 순서를 유지하고, 조용히 잘라내는 대신 AttachedDocumentsTooLarge를 낸다.
        """
        if collection not in ("social", "corporate") or (
            collection == "corporate" and not company_id
        ):
            raise DocumentError("기업 검색에는 company_id가 필요합니다.")
        if collection == "social" and company_id is not None:
            raise DocumentError("사회 검색에는 company_id를 지정하지 않습니다.")
        if document_ids is not None and (not document_ids or collection != "corporate"):
            raise DocumentError("기업 문서 선택 검색에는 비어 있지 않은 document_ids가 필요합니다.")
        scope = _scope(company_id)
        async with self.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n, coalesce(sum(length(c.content)), 0) AS chars "
                "FROM adcheck_rag.chunks c JOIN adcheck_rag.documents d USING(scope,document_id) "
                "WHERE d.scope=%s AND d.corpus=%s "
                "AND (%s::text[] IS NULL OR d.document_id = ANY(%s::text[]))",
                (scope, collection, document_ids, document_ids),
            )
            found = await cur.fetchone()
        if not found["n"]:
            return []
        limit = self.settings.rag_max_attached_chars
        if document_ids is not None and found["chars"] > limit:
            raise AttachedDocumentsTooLarge(found["chars"], limit)
        pieces = await self.embeddings.split(query)
        if not pieces:
            raise DocumentError("검색어에 본문이 없습니다.")
        vectors = await self.embeddings.embed(pieces)
        dim = self.embeddings.dim
        vector = str([sum(v[i] for v in vectors) / len(vectors) for i in range(dim)])
        select = (
            "SELECT d.*,c.chunk_id,c.section,c.content,c.metadata AS chunk_metadata,"
            "1-(c.embedding <=> %s::vector) AS score "
            "FROM adcheck_rag.chunks c JOIN adcheck_rag.documents d USING(scope,document_id) "
            "WHERE d.scope=%s AND d.corpus=%s "
        )
        if document_ids is None:
            sql = select + (
                "AND 1-(c.embedding <=> %s::vector)>=%s "
                "ORDER BY c.embedding <=> %s::vector,c.document_id,c.chunk_id LIMIT %s"
            )
            params = (vector, scope, collection, vector, min_score, vector, top_k)
        else:
            # ordinal이 생기기 전에 저장된 조각은 chunk_id 순서를 따른다.
            sql = select + (
                "AND d.document_id = ANY(%s::text[]) "
                "ORDER BY array_position(%s::text[], d.document_id),"
                "(c.metadata->>'ordinal')::int NULLS LAST,c.chunk_id"
            )
            params = (vector, scope, collection, document_ids, document_ids)
        async with self.connection() as conn:
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
        evidence = []
        for row in rows:
            meta = row["metadata"] | row["chunk_metadata"]
            evidence.append(
                RetrievedEvidence(
                    document=row["title"],
                    section=row["section"],
                    snippet=row["content"],
                    rule_id=meta.get("rule_id", meta.get("row_id", row["document_id"])),
                    version=row["version"],
                    document_id=row["document_id"],
                    chunk_id=row["chunk_id"],
                    company_id=row["company_id"],
                    document_type=row["document_type"],
                    record_type=meta.get("record_type", row["document_type"]),
                    source_urls=meta.get("source_urls", []),
                    source_ids=meta.get("source_ids", []),
                    row_id=meta.get("row_id"),
                    score=row["score"],
                    published_at=meta.get("published_at"),
                    category=meta.get("category"),
                    verification_status=meta.get("verification_status"),
                )
            )
        return evidence
