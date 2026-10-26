import pytest
from app.clients.rag_mcp_client import RetrievalResult
from app.graph.graph import build_graph
from app.graph.nodes.retrieve_corporate_value import retrieve_corporate_value_live
from app.graph.nodes.retrieve_social_context import retrieve_social_context_live
from app.graph.state import initial_state
from app.schemas.review import ReviewRequest


class RagToolsFixture:
    def __init__(self):
        self.companies = []
        self.document_ids = []

    async def search_social_context(self, query):
        return RetrievalResult(
            mock=False,
            status="ok",
            message="",
            related_criteria=["노동·인권 침해 연상 방지"],
            evidence=[
                {
                    "document": "기준",
                    "section": "인권",
                    "snippet": "인권을 존중한다",
                    "rule_id": "R1",
                    "version": "v1",
                    "document_id": "doc1",
                    "chunk_id": "chunk1",
                    "record_type": "project_guideline",
                    "score": 0.8,
                    "source_urls": ["https://example.com/policy"],
                }
            ],
        )

    async def search_corporate_value(self, query, company_id, document_ids=None):
        self.companies.append(company_id)
        self.document_ids.append(document_ids)
        return RetrievalResult(mock=False, message="", evidence=[])


async def test_live_graph_receives_evidence_and_tenant():
    tools = RagToolsFixture()
    state = initial_state(
        ReviewRequest(text="인권", context={"channel": "sns", "company_id": "c1"})
    )
    result = await build_graph(rag_tools=tools).ainvoke(state)
    assert result["social_context_evidence"][0].score == 0.8
    complete = result["social_context_result"].model_dump(mode="json")
    assert complete["related_criteria"] == ["노동·인권 침해 연상 방지"]
    assert complete["status"] == "ok" and complete["mock"] is False
    assert complete["evidence"][0]["chunk_id"] == "chunk1"
    assert complete["evidence"][0]["source_urls"] == ["https://example.com/policy"]
    assert result["corporate_value_result"].status == "empty"
    assert tools.companies == ["c1"]
    assert tools.document_ids == [None]
    assert result["status"] == "needs_review"  # LLM은 아직 mock이다.


async def test_attached_document_ids_reach_corporate_search():
    tools = RagToolsFixture()
    context = {"channel": "sns", "company_id": "c1", "document_ids": ["c1-ethics", "c1-values"]}
    state = initial_state(ReviewRequest(text="인권", context=context))
    await build_graph(rag_tools=tools).ainvoke(state)
    assert tools.document_ids == [["c1-ethics", "c1-values"]]


@pytest.mark.parametrize("document_ids", [[], ["../bad"], ["x" * 151]])
def test_review_request_rejects_invalid_document_ids(document_ids):
    with pytest.raises(ValueError):
        ReviewRequest(text="인권", context={"channel": "sns", "document_ids": document_ids})


async def test_missing_company_does_not_search_another_tenant():
    tools = RagToolsFixture()
    state = initial_state(ReviewRequest(text="인권", context={"channel": "sns"}))
    result = await build_graph(rag_tools=tools).ainvoke(state)
    assert not tools.companies
    assert "COMPANY_NOT_SPECIFIED" in result["rag_errors"]
    assert result["corporate_value_result"] is None


async def test_rag_failure_is_retained_for_human_review():
    class FailedTools(RagToolsFixture):
        async def search_social_context(self, query):
            raise RuntimeError("test failure")

    state = initial_state(ReviewRequest(text="인권", context={"channel": "sns"}))
    result = await build_graph(rag_tools=FailedTools()).ainvoke(state)
    assert result["status"] == "needs_review"
    assert "SOCIAL_RETRIEVAL_FAILED" in result["rag_errors"]
    assert result["social_context_result"].status == "error"
    assert result["social_context_result"].related_criteria == []


@pytest.mark.parametrize(
    "node,result_key,evidence_key",
    [
        (retrieve_social_context_live, "social_context_result", "social_context_evidence"),
        (retrieve_corporate_value_live, "corporate_value_result", "corporate_value_evidence"),
    ],
)
async def test_nodes_store_complete_result_without_deciding_verdict(node, result_key, evidence_key):
    response = RetrievalResult(
        mock=False,
        status="ok",
        message="검색한 기준입니다.",
        related_criteria=["역사적 사건·상징의 상업적 소비 가능성"],
        evidence=[
            {
                "document": "기업 정책",
                "section": "역사 존중",
                "snippet": "역사적 사건을 할인에 사용하지 않는다.",
                "rule_id": "policy-1",
                "version": "v1",
                "document_id": "doc1",
                "chunk_id": "chunk1",
                "company_id": "c1",
                "document_type": "ethics_policy",
                "record_type": "uploaded_company_document",
                "source_urls": ["https://example.com/source"],
                "source_ids": ["source-1"],
                "row_id": "policy-1",
                "score": 0.8,
                "published_at": "2026-10-22",
                "category": "corporate_value",
                "verification_status": "user_provided_not_independently_verified",
            }
        ],
    )

    class Tools:
        async def search_social_context(self, query):
            return response

        async def search_corporate_value(self, query, company_id, document_ids=None):
            return response

    current = initial_state(
        ReviewRequest(text="문구", context={"channel": "sns", "company_id": "c1"})
    )
    update = await node(current, Tools())
    assert set(update) == {result_key, evidence_key}
    assert update[result_key].model_dump(mode="json") == response.model_dump(mode="json")
    assert update[evidence_key] == response.evidence
