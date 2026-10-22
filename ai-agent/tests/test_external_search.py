import asyncio
from datetime import UTC, datetime

import app.graph.graph as graph_module
import pytest
from app.clients.business_mcp_client import RecentIssue, RecentIssueResult
from app.graph.nodes.retrieve_external_evidence import retrieve_external_evidence
from app.graph.state import ReviewState, initial_state
from app.schemas.review import Evidence, ReviewRequest


class FakeBusinessTools:
    def __init__(self, status: str = "ok") -> None:
        self.calls = 0
        self.status = status

    async def search_recent_issue(self, query: str) -> RecentIssueResult:
        self.calls += 1
        return RecentIssueResult(
            status=self.status,
            mock=False,
            message="테스트 결과",
            results=[
                RecentIssue(
                    title="합성 결과",
                    url="https://example.com/1",
                    snippet="검색 근거",
                    source="example.com",
                    retrieved_at=datetime.now(UTC),
                )
            ]
            if self.status == "ok"
            else [],
        )


def state() -> ReviewState:
    return initial_state(ReviewRequest(text="광고 문구", context={"channel": "sns"}))


@pytest.mark.parametrize("status", ["ok", "empty", "timeout", "unavailable", "error"])
async def test_graph_search_once_and_no_automatic_pass(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    review_calls = 0

    def reviewer(state: ReviewState) -> dict:
        nonlocal review_calls
        review_calls += 1
        return {
            "external_search_query": "최근 이슈",
            "evidence_sufficient": False,
            "risk": "uncertain",
            "summary": "근거 부족",
        }

    monkeypatch.setattr(graph_module, "review_llm", reviewer)
    tools = FakeBusinessTools(status)
    result = await graph_module.build_graph(tools).ainvoke(state())
    assert tools.calls == 1
    assert review_calls == 2  # Empty results and failures also reach the final reviewer.
    assert result["external_search_attempted"] is True
    assert result["status"] == "needs_review"
    assert result["external_search_result"].status == status
    if status == "ok":
        assert str(result["external_evidence"][0].url) == "https://example.com/1"


@pytest.mark.parametrize("sufficient, query", [(True, "최근 이슈"), (False, None), (False, " ")])
async def test_skip_when_sufficient_or_no_eligible_query(
    monkeypatch: pytest.MonkeyPatch, sufficient: bool, query: str | None
) -> None:
    def reviewer(state: ReviewState) -> dict:
        return {
            "external_search_query": query,
            "evidence_sufficient": sufficient,
            "risk": "no" if sufficient else "uncertain",
            "summary": "테스트",
        }

    monkeypatch.setattr(graph_module, "review_llm", reviewer)
    tools = FakeBusinessTools()
    result = await graph_module.build_graph(tools).ainvoke(state())
    assert tools.calls == 0
    assert result["status"] == ("pass" if sufficient else "needs_review")


async def test_search_success_reassessed_by_reviewer(monkeypatch: pytest.MonkeyPatch) -> None:
    def reviewer(state: ReviewState) -> dict:
        enough = bool(state["external_evidence"])
        return {
            "external_search_query": "최근 이슈",
            "evidence_sufficient": enough,
            "risk": "no" if enough else "uncertain",
            "summary": "테스트 판정",
        }

    monkeypatch.setattr(graph_module, "review_llm", reviewer)
    tools = FakeBusinessTools()
    result = await graph_module.build_graph(tools).ainvoke(state())
    assert tools.calls == 1 and result["status"] == "pass"


async def test_agent_total_timeout() -> None:
    class SlowTools:
        async def search_recent_issue(self, query: str) -> RecentIssueResult:
            await asyncio.sleep(10)
            pytest.fail("Should be cancelled")

    current = state()
    current["external_search_query"] = "최근 이슈"
    result = await asyncio.wait_for(
        retrieve_external_evidence(current, SlowTools(), timeout_seconds=0.02), timeout=1
    )
    assert result["external_search_attempted"] is True
    assert result["external_search_result"].status == "timeout"


async def test_search_budget_is_per_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def reviewer(state: ReviewState) -> dict:
        return {"external_search_query": "공개 사실 확인", "summary": "근거 부족"}

    monkeypatch.setattr(graph_module, "review_llm", reviewer)
    tools = FakeBusinessTools()
    graph = graph_module.build_graph(tools)
    for _ in range(2):
        result = await graph.ainvoke(state())
        assert result["status"] == "needs_review"
    assert tools.calls == 2


async def test_empty_external_result_does_not_override_internal_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = Evidence(document="합성 기준", section="일반 표현", snippet="테스트용 근거")

    def reviewer(state: ReviewState) -> dict:
        # Simulate the final reviewer accepting existing RAG evidence after an empty web search.
        enough = state["external_search_attempted"] and bool(state["social_context_evidence"])
        return {
            "external_search_query": "추가 공개 사실 확인",
            "evidence_sufficient": enough,
            "risk": "no" if enough else "uncertain",
            "summary": "최종 판정 노드의 결과",
        }

    monkeypatch.setattr(graph_module, "review_llm", reviewer)
    monkeypatch.setattr(
        graph_module,
        "retrieve_social_context",
        lambda state: {"social_context_evidence": [evidence]},
    )
    tools = FakeBusinessTools("empty")
    result = await graph_module.build_graph(tools).ainvoke(state())
    assert tools.calls == 1
    assert result["social_context_evidence"] == [evidence]
    assert result["external_evidence"] == []
    assert result["status"] == "pass"


@pytest.mark.parametrize("status", ["empty", "error", "timeout", "unavailable"])
async def test_search_node_does_not_decide_summary_or_status(status: str) -> None:
    current = state()
    current["external_search_query"] = "공개 사실 확인"
    result = await retrieve_external_evidence(current, FakeBusinessTools(status))
    assert "summary" not in result and "status" not in result
    assert result["external_search_result"].status == status
