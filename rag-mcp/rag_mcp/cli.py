import argparse
import asyncio
import json
from pathlib import Path

from rag_mcp.config import ROOT, Settings
from rag_mcp.documents import corporate_document, parse_policies, social_documents
from rag_mcp.retrieval.embeddings import LocalEmbeddings
from rag_mcp.retrieval.vector_store import PgVectorStore


async def execute(args: argparse.Namespace) -> None:
    settings = Settings()
    embeddings = LocalEmbeddings(settings)
    store = PgVectorStore(settings, embeddings)
    if args.command == "init-db":
        await store.initialize()
        print("pgvector schema initialized")
        return
    await store.ready()
    if args.command == "ingest-social":
        documents = await social_documents(args.data_dir, embeddings)
    else:
        rows = parse_policies(args.file.name, args.file.read_bytes(), settings)
        documents = [await corporate_document(rows, embeddings)]
    for document in documents:
        result = await store.replace(document)
        print(json.dumps(result.model_dump(), ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="AdCheck pgvector schema / corpus management")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    social = commands.add_parser("ingest-social")
    social.add_argument("--data-dir", type=Path, default=ROOT / "rag-mcp" / "data")
    corporate = commands.add_parser("ingest-corporate")
    corporate.add_argument("file", type=Path, help="A single CSV or XLSX corporate document")
    args = parser.parse_args()
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
