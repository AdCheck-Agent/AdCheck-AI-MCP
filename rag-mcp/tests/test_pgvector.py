import pytest
from rag_mcp.documents import corporate_document
from rag_mcp.errors import DocumentError, EmbeddingUnavailable
from rag_mcp.schemas import PolicyRow


def policy(company="test_a", content="인권 노동 존중", synthetic=False):
    return PolicyRow(
        row_id="p1",
        company_id=company,
        document_id="policy",
        document_type="ethics_policy",
        title="정책",
        section="인권",
        content=content,
        version="v1",
        synthetic=synthetic,
    )


async def test_save_search_tenant_delete_and_idempotency(db_store, embeddings):
    doc = await corporate_document([policy()], embeddings)
    result = await db_store.replace(doc, expected_revision=0)
    assert result.revision == 1
    assert (await db_store.replace(doc)).revision == 1
    await db_store.replace(await corporate_document([policy("test_b")], embeddings))
    found = await db_store.search("인권 노동", collection="corporate", company_id="test_a")
    assert found and all(e.company_id == "test_a" and not e.synthetic for e in found)
    assert found[0].score > 0.5
    assert await db_store.search("인권", collection="corporate", company_id="missing") == []
    assert await db_store.search("인권", collection="social") == []
    await db_store.delete("test_a", "policy")
    assert await db_store.search("인권", collection="corporate", company_id="test_a") == []
    assert await db_store.search("인권", collection="corporate", company_id="test_b")


async def test_atomic_replace_and_revision_conflict(db_store, embeddings):
    original = await corporate_document([policy()], embeddings)
    await db_store.replace(original)
    replacement = await corporate_document([policy(content="환경 포장 개선")], embeddings)
    with pytest.raises(DocumentError) as error:
        await db_store.replace(replacement, expected_revision=0)
    assert error.value.status == 409
    assert (await db_store.get("test_a", "policy")).revision == 1
    assert (await db_store.replace(replacement, expected_revision=1)).revision == 2
    async with db_store.connection() as conn:
        cur = await conn.execute("SELECT content FROM adcheck_rag.chunks")
        assert [r["content"] for r in await cur.fetchall()] == ["환경 포장 개선"]


async def test_synthetic_excluded_unless_requested(db_store, embeddings):
    await db_store.replace(await corporate_document([policy(synthetic=True)], embeddings))
    assert await db_store.search("인권", collection="corporate", company_id="test_a") == []
    assert (
        await db_store.search(
            "인권", collection="corporate", company_id="test_a", include_synthetic=True
        )
    )[0].synthetic


async def test_bad_embedding_does_not_erase_previous(db_store, embeddings, monkeypatch):
    await db_store.replace(await corporate_document([policy()], embeddings))

    async def failure(texts):
        raise EmbeddingUnavailable("test failure")

    monkeypatch.setattr(embeddings, "embed", failure)
    with pytest.raises(EmbeddingUnavailable):
        await db_store.replace(await corporate_document([policy(content="new")], embeddings))
    assert (await db_store.get("test_a", "policy")).revision == 1


async def test_missing_delete_get_are_404(db_store):
    with pytest.raises(DocumentError) as error:
        await db_store.get("test_a", "missing")
    assert error.value.status == 404
    with pytest.raises(DocumentError):
        await db_store.delete("test_a", "missing")
