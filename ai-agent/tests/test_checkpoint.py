import asyncio

import app.graph.graph as graph_module
from app.checkpoint import CheckpointSink
from app.clients.business_mcp_client import CheckpointResult
from app.events import Stage, StageEvent, StageStatus, StageTracker, current_tracker
from app.graph.state import initial_state
from app.schemas.review import ReviewRequest

ID = "550e8400-e29b-41d4-a716-446655440000"
OK = CheckpointResult(status="ok", message="ok")


class Tools:
    def __init__(self, results=None, delay=0.0) -> None:
        self.calls: list[tuple[str, str]] = []
        self.results = list(results or [])
        self.delay = delay

    async def save_checkpoint(self, original_text_id, checkpoint_level):
        await asyncio.sleep(self.delay)
        self.calls.append((original_text_id, checkpoint_level))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return OK


def sink(tools, original_text_id=ID) -> CheckpointSink:
    return CheckpointSink(tools, original_text_id, "t1", asyncio.get_running_loop())


def event(stage, status) -> StageEvent:
    return StageEvent(ID, "t1", stage, status)


async def test_only_finished_stages_are_saved_in_order_then_completed() -> None:
    tools = Tools(delay=0.01)
    s = sink(tools)
    for stage in (Stage.BANNED_WORD_CHECK, Stage.SOCIAL_HISTORICAL_SEARCH):
        s.emit(event(stage, StageStatus.RUNNING))
        s.emit(event(stage, StageStatus.SUCCEEDED))
    s.emit(event(Stage.COMPANY_VALUES_SEARCH, StageStatus.SKIPPED))
    s.emit(event(Stage.FINAL_ASSESSMENT, StageStatus.FAILED))
    s.complete()
    await s.close()
    assert tools.calls == [
        (ID, "BANNED_WORD_CHECK"),
        (ID, "SOCIAL_HISTORICAL_SEARCH"),
        (ID, "COMPLETED"),
    ]


async def test_no_review_id_sends_nothing() -> None:
    tools = Tools()
    s = sink(tools, original_text_id=None)
    s.emit(event(Stage.BANNED_WORD_CHECK, StageStatus.SUCCEEDED))
    s.complete()
    await s.close()
    assert tools.calls == []


async def test_retryable_failure_retried_once_before_next_stage() -> None:
    retry = CheckpointResult(status="error", retryable=True, message="5xx")
    tools = Tools([retry, OK])
    s = sink(tools)
    s.emit(event(Stage.BANNED_WORD_CHECK, StageStatus.SUCCEEDED))
    s.emit(event(Stage.SOCIAL_HISTORICAL_SEARCH, StageStatus.SUCCEEDED))
    await s.close()
    assert [level for _, level in tools.calls] == [
        "BANNED_WORD_CHECK",
        "BANNED_WORD_CHECK",
        "SOCIAL_HISTORICAL_SEARCH",
    ]


async def test_rejected_or_crashing_calls_do_not_retry_or_stop_the_rest() -> None:
    rejected = CheckpointResult(status="error", http_status=404, retryable=False, message="no")
    tools = Tools([rejected, RuntimeError("down"), OK, OK])
    s = sink(tools)
    s.emit(event(Stage.BANNED_WORD_CHECK, StageStatus.SUCCEEDED))
    s.emit(event(Stage.SOCIAL_HISTORICAL_SEARCH, StageStatus.SUCCEEDED))
    await s.close()
    levels = [level for _, level in tools.calls]
    assert levels[0] == "BANNED_WORD_CHECK" and levels.count("BANNED_WORD_CHECK") == 1
    assert levels[-1] == "SOCIAL_HISTORICAL_SEARCH"


async def test_events_from_worker_threads_keep_order() -> None:
    tools = Tools()
    s = sink(tools)
    stages = [Stage.BANNED_WORD_CHECK, Stage.SOCIAL_HISTORICAL_SEARCH, Stage.FINAL_ASSESSMENT]

    def from_thread() -> None:
        for stage in stages:
            s.emit(event(stage, StageStatus.SUCCEEDED))

    await asyncio.to_thread(from_thread)
    await s.close()
    assert [level for _, level in tools.calls] == [stage.value for stage in stages]


async def test_slow_backend_does_not_hold_review_past_the_flush_timeout() -> None:
    tools = Tools(delay=5)
    s = sink(tools)
    s.emit(event(Stage.BANNED_WORD_CHECK, StageStatus.SUCCEEDED))
    started = asyncio.get_running_loop().time()
    await s.close(timeout=0.1)
    assert asyncio.get_running_loop().time() - started < 1


async def test_real_graph_run_saves_every_stage_then_completed() -> None:
    tools = Tools()
    state = initial_state(
        ReviewRequest(text="정상적인 사람이 아닙니다", context={"channel": "sns"}, review_id=ID)
    )
    s = sink(tools)
    token = current_tracker.set(StageTracker(ID, state["trace_id"], s))
    try:
        await graph_module.build_graph().ainvoke(state)
    finally:
        current_tracker.reset(token)
    s.complete()
    await s.close()
    levels = [level for _, level in tools.calls]
    assert levels[0] == "BANNED_WORD_CHECK"
    assert levels[-2:] == ["OUTPUT_VALIDATION", "COMPLETED"]
    assert "COMPANY_VALUES_SEARCH" not in levels  # skipped stage is not saved


def _post(tools, monkeypatch, *, break_graph=False, review_id=ID):
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        app.state.checkpoint_tools = tools
        if break_graph:

            class Broken:
                async def ainvoke(self, state):
                    raise RuntimeError("boom")

            app.state.review_graph = Broken()
        body = {"text": "새로운 상품", "context": {"channel": "sns"}}
        if review_id:
            body["review_id"] = review_id
        return client.post("/api/v1/reviews", json=body)


def test_route_saves_stages_then_completed(monkeypatch) -> None:
    tools = Tools()
    response = _post(tools, monkeypatch)
    levels = [level for _, level in tools.calls]
    assert response.status_code == 200
    assert levels[0] == "BANNED_WORD_CHECK"
    assert levels[-2:] == ["OUTPUT_VALIDATION", "COMPLETED"]
    assert {original for original, _ in tools.calls} == {ID}


def test_route_failed_review_is_never_completed(monkeypatch) -> None:
    tools = Tools()
    response = _post(tools, monkeypatch, break_graph=True)
    assert response.status_code == 500
    assert "COMPLETED" not in [level for _, level in tools.calls]


def test_route_backend_down_does_not_fail_the_review(monkeypatch) -> None:
    tools = Tools([RuntimeError("down")] * 20)
    assert _post(tools, monkeypatch).status_code == 200


def test_route_without_tools_or_review_id_is_unchanged(monkeypatch) -> None:
    assert _post(None, monkeypatch).status_code == 200
    tools = Tools()
    assert _post(tools, monkeypatch, review_id=None).status_code == 200
    assert tools.calls == []
