import json
from datetime import UTC, datetime

import app.graph.graph as graph_module
import pytest
from app.clients.business_mcp_client import RecentIssue, RecentIssueResult
from app.graph.nodes.review_llm import review_llm
from app.graph.state import initial_state
from app.llm.client import set_review_model
from app.llm.evidence import to_evidence
from app.schemas.review import ReviewRequest, ReviewResponse

TEXT = "5월 18일 기념 탱크데이 특별 할인"


class FakeModel:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = 0

    def generate(self, system: str, user: str) -> str:
        self.calls += 1
        return self.responses.pop(0)


class FakeBusinessTools:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search_recent_issue(self, query: str) -> RecentIssueResult:
        self.queries.append(query)
        return RecentIssueResult(
            status="ok",
            mock=False,
            message="ok",
            results=[
                RecentIssue(
                    title="탱크데이 논란 보도",
                    url="https://news.example.com/1",
                    snippet="한 기업의 탱크데이 이벤트가 논란이 되었다.",
                    source="news.example.com",
                    retrieved_at=datetime.now(UTC),
                )
            ],
        )


def judgment(**kw) -> str:
    data = {
        "risk": "uncertain",
        "evidence_sufficient": False,
        "summary": "근거 부족",
        "findings": [],
        "external_search_query": None,
    }
    return json.dumps({**data, **kw}, ensure_ascii=False)


def state():
    return initial_state(ReviewRequest(text=TEXT, context={"channel": "sns"}))


def test_external_hit_is_mapped_to_evidence_with_url() -> None:
    issue = RecentIssue(
        title="보도",
        url="https://news.example.com/1",
        snippet="내용",
        source="news.example.com",
        retrieved_at=datetime.now(UTC),
    )
    evidence = to_evidence(issue)
    assert evidence.document == "보도"
    assert "https://news.example.com/1" in evidence.section


def test_model_may_request_one_search_when_evidence_is_short() -> None:
    set_review_model(FakeModel(judgment(external_search_query="  탱크데이   이벤트 논란 ")))
    result = review_llm(state())
    assert result["external_search_query"] == "탱크데이 이벤트 논란"
    assert result["evidence_sufficient"] is False


@pytest.mark.parametrize("query", [None, "", "   ", "가" * 401])
def test_no_query_when_missing_or_too_long(query: str | None) -> None:
    set_review_model(FakeModel(judgment(external_search_query=query)))
    assert "external_search_query" not in review_llm(state())


def test_no_second_search_once_attempted() -> None:
    current = state()
    current["external_search_attempted"] = True
    set_review_model(FakeModel(judgment(external_search_query="또 검색")))
    assert "external_search_query" not in review_llm(current)


def test_search_service_failure_skips_model_and_needs_review() -> None:
    model = FakeModel()
    set_review_model(model)
    current = state()
    current["rag_errors"] = ["SOCIAL_RETRIEVAL_FAILED"]
    result = review_llm(current)
    assert result["risk"] == "uncertain"
    assert model.calls == 0


async def test_graph_async_external_search_flow() -> None:
    finding = {
        "category": "historical_context",
        "severity": "high",
        "quote": "탱크데이",
        "reason": "보도된 논란과 같은 표현입니다.",
        "evidence_ids": ["E1"],
        "needs_human_review": False,
    }
    first = judgment(external_search_query="탱크데이 이벤트 논란")
    second = judgment(risk="yes", evidence_sufficient=True, summary="수정 필요", findings=[finding])
    alternative = json.dumps({"suggestions": [{"index": 0, "suggestion": "봄맞이 감사 할인"}]})
    clean = judgment(risk="no", findings=[])  # the fixed ad, judged again
    model = FakeModel(first, second, alternative, clean)
    set_review_model(model)
    tools = FakeBusinessTools()

    graph = graph_module.build_graph(business_tools=tools)
    result = ReviewResponse.model_validate(await graph.ainvoke(state()))

    assert tools.queries == ["탱크데이 이벤트 논란"]
    assert model.calls == 4  # judge, judge after search, suggestion, judge of the fixed ad
    assert result.status == "revise"
    assert result.findings[0].suggestion == "봄맞이 감사 할인"
    assert "news.example.com" in result.findings[0].evidence[0].section
