import pytest
from rag_mcp.documents import corporate_document
from rag_mcp.errors import AttachedDocumentsTooLarge, DocumentError, EmbeddingUnavailable
from rag_mcp.schemas import PolicyRow


def policy(company="test_a", content="인권 노동 존중"):
    return PolicyRow(
        row_id="p1",
        company_id=company,
        document_id="policy",
        document_type="ethics_policy",
        title="정책",
        section="인권",
        content=content,
    )


async def test_save_search_tenant_delete_and_idempotency(db_store, embeddings):
    doc = await corporate_document([policy()], embeddings)
    result = await db_store.replace(doc, expected_revision=0)
    assert (result.revision, result.version) == (1, "v1")
    assert (await db_store.replace(doc)).version == "v1"  # identical re-upload
    await db_store.replace(await corporate_document([policy("test_b")], embeddings))
    found = await db_store.search("인권 노동", collection="corporate", company_id="test_a")
    assert found and all(e.company_id == "test_a" for e in found)
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
    replaced = await db_store.replace(replacement, expected_revision=1)
    assert (replaced.revision, replaced.version) == (2, "v2")
    found = await db_store.search("환경", collection="corporate", company_id="test_a")
    assert {e.version for e in found} == {"v2"}
    async with db_store.connection() as conn:
        cur = await conn.execute("SELECT content FROM adcheck_rag.chunks")
        assert [r["content"] for r in await cur.fetchall()] == ["환경 포장 개선"]


async def test_attached_documents_return_every_chunk_in_file_order(db_store, embeddings):
    rows = [
        policy(content=content).model_copy(update={"row_id": f"p{i}", "section": f"s{i}"})
        for i, content in enumerate(["환경 포장", "인권 노동 존중", "고객 존중"], 1)
    ]
    await db_store.replace(await corporate_document(rows, embeddings))
    other = policy(content="인권").model_copy(update={"document_id": "other"})
    await db_store.replace(await corporate_document([other], embeddings))

    found = await db_store.search(
        "인권",
        collection="corporate",
        company_id="test_a",
        document_ids=["other", "policy"],
        top_k=1,
        min_score=1.0,
    )
    # top_k / min_score do not apply; attachment order, then file row order.
    assert [(e.document_id, e.row_id) for e in found] == [
        ("other", "p1"),
        ("policy", "p1"),
        ("policy", "p2"),
        ("policy", "p3"),
    ]
    ranked = await db_store.search("인권", collection="corporate", company_id="test_a", top_k=1)
    assert len(ranked) == 1


async def test_attached_documents_over_limit_are_not_truncated(db_store, embeddings):
    await db_store.replace(await corporate_document([policy(content="가" * 50)], embeddings))
    db_store.settings = db_store.settings.model_copy(update={"rag_max_attached_chars": 49})
    with pytest.raises(AttachedDocumentsTooLarge) as error:
        await db_store.search(
            "인권", collection="corporate", company_id="test_a", document_ids=["policy"]
        )
    assert error.value.chars == 50 and error.value.limit == 49
    # The limit applies to attached files only; ranked search still returns top_k.
    assert await db_store.search("인권", collection="corporate", company_id="test_a")


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


async def test_selected_documents_filter_before_top_k_and_keep_tenant_scope(db_store, embeddings):
    for company, doc_id, content in (
        ("test_a", "selected", "인권 노동 존중"),
        ("test_a", "unselected", "인권"),
        ("test_b", "selected", "인권"),
        ("test_b", "other_company_only", "인권"),
    ):
        row = policy(company, content).model_copy(update={"document_id": doc_id})
        await db_store.replace(await corporate_document([row], embeddings))

    found = await db_store.search(
        "인권", collection="corporate", company_id="test_a", document_ids=["selected"], top_k=1
    )
    assert len(found) == 1
    assert found[0].document_id == "selected" and found[0].company_id == "test_a"
    for ids in (["missing"], ["other_company_only"]):
        assert (
            await db_store.search(
                "인권", collection="corporate", company_id="test_a", document_ids=ids
            )
            == []
        )
    both = await db_store.search(
        "인권",
        collection="corporate",
        company_id="test_a",
        document_ids=["selected", "unselected"],
    )
    assert {e.document_id for e in both} == {"selected", "unselected"}
    assert all(e.company_id == "test_a" for e in both)
    with pytest.raises(DocumentError):
        await db_store.search("인권", collection="corporate", company_id="test_a", document_ids=[])
