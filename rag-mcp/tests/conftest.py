import hashlib
import os

import pytest
import pytest_asyncio
from rag_mcp.config import Settings
from rag_mcp.retrieval.vector_store import PgVectorStore


class TestEmbeddings:
    profile = "test-only:384"

    async def split(self, text: str) -> list[str]:
        return [text[i : i + 100] for i in range(0, len(text), 100)]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            vector = [0.0] * 384
            for word in text.split():
                index = int(hashlib.sha256(word.encode()).hexdigest(), 16) % 384
                vector[index] += 1.0
            if not any(vector):
                vector[0] = 1.0
            result.append(vector)
        return result


@pytest.fixture
def embeddings() -> TestEmbeddings:
    return TestEmbeddings()


@pytest_asyncio.fixture
async def db_store(embeddings):
    url = os.getenv("RAG_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set RAG_TEST_DATABASE_URL to a dedicated *_test database")
    from psycopg.conninfo import conninfo_to_dict

    assert conninfo_to_dict(url)["dbname"].endswith("_test"), "Test DB must end in _test"
    store = PgVectorStore(Settings(rag_database_url=url), embeddings)
    await store.initialize()
    async with store.connection() as conn:
        await conn.execute("DELETE FROM adcheck_rag.documents")
    yield store
    async with store.connection() as conn:
        await conn.execute("DELETE FROM adcheck_rag.documents")
