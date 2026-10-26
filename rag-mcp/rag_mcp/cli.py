import argparse
import asyncio
import json
import math
import time
from pathlib import Path

from rag_mcp.config import ROOT, Settings
from rag_mcp.documents import (
    corporate_document,
    parse_policies,
    sample_identity,
    social_documents,
)
from rag_mcp.retrieval.embeddings import LocalEmbeddings
from rag_mcp.retrieval.vector_store import PgVectorStore


async def check_embedding(settings: Settings, embeddings: LocalEmbeddings) -> None:
    """설정된 모델을 한 번 불러와 결과를 보고한다. DB는 필요 없다."""
    texts = [
        "5월 18일 기념 탱크데이 특가",
        "5·18 기념일에 맞춘 탱크데이 할인",
        "봄맞이 신메뉴 출시",
    ]
    started = time.perf_counter()
    vectors = await embeddings.embed(texts)
    seconds = round(time.perf_counter() - started, 1)

    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    pieces = await embeddings.split("광고 문구 " * 600)
    print(
        json.dumps(
            {
                "model": settings.rag_embedding_model,
                "dim": len(vectors[0]),
                "expected_dim": settings.rag_embedding_dim,
                "norm": round(math.sqrt(cosine(vectors[0], vectors[0])), 4),
                "similar_pair": round(cosine(vectors[0], vectors[1]), 3),
                "unrelated_pair": round(cosine(vectors[0], vectors[2]), 3),
                "first_load_and_embed_seconds": seconds,
                "chunk_tokens": settings.rag_chunk_tokens,
                "chunks_for_long_text": len(pieces),
            },
            ensure_ascii=False,
        )
    )


async def execute(args: argparse.Namespace) -> None:
    settings = Settings()
    embeddings = LocalEmbeddings(settings)
    if args.command == "check-embedding":
        await check_embedding(settings, embeddings)
        return
    store = PgVectorStore(settings, embeddings)
    if args.command == "init-db":
        await store.initialize()
        print("pgvector schema initialized")
        return
    await store.ready()
    if args.command == "ingest-social":
        documents = await social_documents(args.data_dir, embeddings)
    else:
        default_company, default_document = sample_identity(args.file)
        rows = parse_policies(
            args.file.name,
            args.file.read_bytes(),
            settings,
            args.company_id or default_company,
            args.document_id or default_document,
        )
        documents = [await corporate_document(rows, embeddings)]
    for document in documents:
        result = await store.replace(document)
        print(json.dumps(result.model_dump(), ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="AdCheck pgvector schema / corpus management")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    commands.add_parser("check-embedding", help="Load the embedding model and print a summary")
    social = commands.add_parser("ingest-social")
    social.add_argument("--data-dir", type=Path, default=ROOT / "rag-mcp" / "data")
    corporate = commands.add_parser("ingest-corporate")
    corporate.add_argument("file", type=Path, help="A single CSV or XLSX corporate document")
    corporate.add_argument("--company-id", help="Default: the file's folder name")
    corporate.add_argument("--document-id", help="Default: {folder}-{file name}")
    args = parser.parse_args()
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
