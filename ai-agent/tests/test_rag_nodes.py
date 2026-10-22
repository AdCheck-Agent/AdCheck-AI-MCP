from app.clients.rag_mcp_client import RetrievalResult
from app.graph.graph import build_graph
from app.graph.state import initial_state
from app.schemas.review import ReviewRequest


class RagToolsFixture:
    def __init__(self):
        self.companies = []

    async def search_social_context(self, query):
        return RetrievalResult(
            mock=False,
            status="ok",
            message="",
            evidence=[
                {
                    "document": "기준",
                    "section": "인권",
                    "snippet": "인권을 존중한다",
                    "rule_id": "R1",
                    "score": 0.8,
                    "source_urls": ["https://example.com/policy"],
                }
            ],
        )

    async def search_corporate_value(self, query, company_id):
        self.companies.append(company_id)
        return RetrievalResult(mock=False, message="", evidence=[])


async def test_live_graph_receives_evidence_and_tenant():
    tools = RagToolsFixture()
    state = initial_state(
        ReviewRequest(text="인권", context={"channel": "sns", "company_id": "c1"})
    )
    result = await build_graph(rag_tools=tools).ainvoke(state)
    assert result["social_context_evidence"][0].score == 0.8
    assert tools.companies == ["c1"]
    assert result["status"] == "needs_review"  # LLM is still a mock.


async def test_missing_company_does_not_search_another_tenant():
    tools = RagToolsFixture()
    state = initial_state(ReviewRequest(text="인권", context={"channel": "sns"}))
    result = await build_graph(rag_tools=tools).ainvoke(state)
    assert not tools.companies
    assert "COMPANY_NOT_SPECIFIED" in result["rag_errors"]


async def test_rag_failure_is_retained_for_human_review():
    class FailedTools(RagToolsFixture):
        async def search_social_context(self, query):
            raise RuntimeError("test failure")

    state = initial_state(ReviewRequest(text="인권", context={"channel": "sns"}))
    result = await build_graph(rag_tools=FailedTools()).ainvoke(state)
    assert result["status"] == "needs_review"
    assert "SOCIAL_RETRIEVAL_FAILED" in result["rag_errors"]
