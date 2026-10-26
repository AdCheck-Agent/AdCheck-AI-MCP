import app.graph.graph as graph_module
import pytest
from app.events import Stage, StageEvent, StageStatus, StageTracker, current_tracker
from app.graph.graph import tracked
from app.graph.nodes.validate_result import validate_result
from app.graph.state import initial_state
from app.llm.judge import build_user_prompt
from app.schemas.review import ReviewRequest
from pydantic import ValidationError

S, T = Stage, StageStatus


class ListSink:
    def __init__(self) -> None:
        self.events: list[StageEvent] = []

    def emit(self, event: StageEvent) -> None:
        self.events.append(event)

    def pairs(self) -> list[tuple[Stage, StageStatus]]:
        return [(e.stage, e.status) for e in self.events]


def request(**extra) -> ReviewRequest:
    return ReviewRequest(text="정상적인 사람이 아닙니다", context={"channel": "sns"}, **extra)


async def run_graph(sink: ListSink, **extra) -> dict:
    state = initial_state(request(**extra))
    tracker = StageTracker(state["review_id"], state["trace_id"], sink)
    token = current_tracker.set(tracker)
    try:
        return await graph_module.build_graph().ainvoke(state)
    finally:
        current_tracker.reset(token)


async def test_every_stage_reports_and_skipped_ones_are_marked() -> None:
    sink = ListSink()
    await run_graph(sink, review_id="rev_001")

    assert {e.review_id for e in sink.events} == {"rev_001"}
    pairs = sink.pairs()
    # 단계는 순서대로 실행되고, 각각 실행된 뒤 성공한다.
    assert pairs[:4] == [
        (S.BANNED_WORD_CHECK, T.RUNNING),
        (S.BANNED_WORD_CHECK, T.SUCCEEDED),
        (S.SOCIAL_HISTORICAL_SEARCH, T.RUNNING),
        (S.SOCIAL_HISTORICAL_SEARCH, T.SUCCEEDED),
    ]
    # 기업 없음, 외부 검색 없음, revise 아님: 그 단계는 조용히 빠지지 않고 건너뜀으로 남는다.
    assert (S.COMPANY_VALUES_SEARCH, T.SKIPPED) in pairs
    assert (S.EXTERNAL_SEARCH, T.SKIPPED) in pairs
    assert (S.ALTERNATIVE_GENERATION, T.SKIPPED) in pairs
    assert pairs[-2:] == [(S.OUTPUT_VALIDATION, T.RUNNING), (S.OUTPUT_VALIDATION, T.SUCCEEDED)]
    assert "COMPLETED" not in {s.value for s in Stage}


async def test_failed_node_reports_failed_and_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(state):
        raise RuntimeError("boom")

    monkeypatch.setattr(graph_module, "rule_filter", boom)
    sink = ListSink()
    with pytest.raises(RuntimeError):
        await run_graph(sink)
    assert sink.pairs() == [(S.BANNED_WORD_CHECK, T.RUNNING), (S.BANNED_WORD_CHECK, T.FAILED)]


def test_sink_failure_never_breaks_the_review() -> None:
    class BrokenSink:
        def emit(self, event: StageEvent) -> None:
            raise OSError("backend down")

    tracker = StageTracker("rev", "trace_x", BrokenSink())
    tracker.emit(S.BANNED_WORD_CHECK, T.RUNNING)
    assert tracker.statuses[S.BANNED_WORD_CHECK] == T.RUNNING


def test_keep_running_holds_the_stage_open() -> None:
    sink = ListSink()
    tracker = StageTracker(None, "trace_x", sink)
    node = tracked(S.FINAL_ASSESSMENT, lambda state: {}, keep_running=lambda s, u: True)
    token = current_tracker.set(tracker)
    try:
        node(initial_state(request()))
    finally:
        current_tracker.reset(token)
    assert sink.pairs() == [(S.FINAL_ASSESSMENT, T.RUNNING)]


def test_fail_running_marks_only_the_open_stage() -> None:
    tracker = StageTracker(None, "trace_x", ListSink())
    tracker.emit(S.BANNED_WORD_CHECK, T.SUCCEEDED)
    tracker.emit(S.SOCIAL_HISTORICAL_SEARCH, T.RUNNING)
    tracker.fail_running()
    assert tracker.statuses[S.BANNED_WORD_CHECK] == T.SUCCEEDED
    assert tracker.statuses[S.SOCIAL_HISTORICAL_SEARCH] == T.FAILED


def test_request_accepts_new_backend_fields() -> None:
    req = ReviewRequest(
        text="봄 할인",
        review_id="rev_001",
        context={
            "channel": "sns",
            "campaign_purpose": "상품 판매",
            "scheduled_at": "2026-11-11T10:00:00+09:00",
        },
    )
    assert req.review_id == "rev_001"
    assert req.context.scheduled_at.utcoffset() is not None


def test_request_rejects_date_without_timezone_and_bad_review_id() -> None:
    with pytest.raises(ValidationError):
        ReviewRequest(text="x", context={"channel": "sns", "scheduled_at": "2026-11-11T10:00:00"})
    with pytest.raises(ValidationError):
        ReviewRequest(text="x", context={"channel": "sns"}, review_id="bad id!")


def test_posting_date_reaches_the_judge_prompt_only_when_given() -> None:
    plain = initial_state(request())
    assert "<context>" not in build_user_prompt(plain, [])
    dated = initial_state(
        ReviewRequest(
            text="x",
            context={
                "channel": "sns",
                "campaign_purpose": "상품 판매",
                "scheduled_at": "2026-05-18T10:00:00+09:00",
            },
        )
    )
    prompt = build_user_prompt(dated, [])
    assert "<context>" in prompt and "2026-05-18T10:00:00+09:00" in prompt


def test_agent_findings_are_semantic_even_for_legacy_banned_type() -> None:
    from app.llm.spans import locate_findings
    from app.schemas.review import Finding

    item = Finding(
        detection_type="BANNED_WORD",
        category="social_issue",
        severity="high",
        quote="위험 문구",
        reason="확인",
        needs_human_review=True,
    )
    assert locate_findings("위험 문구", [item])[0].detection_type == "SEMANTIC"


def test_missing_information_names_the_gaps() -> None:
    state = initial_state(request())
    state["status"] = "needs_review"
    state["summary"] = "x"
    assert validate_result(state).get("missing_information") is None
    state["rag_errors"] = ["COMPANY_NOT_SPECIFIED", "SOCIAL_RETRIEVAL_FAILED"]
    missing = validate_result(state)["missing_information"]
    assert any("기업 ID" in m for m in missing)
    assert any("검색에 실패" in m for m in missing)
