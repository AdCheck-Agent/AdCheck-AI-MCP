"""단계 진행 이벤트: 검수의 어느 단계가 실행 중·완료·건너뜀·실패인지 알린다.

Agent는 이벤트를 만들기만 한다. 이벤트를 어디로 보낼지(BE API, 스트림)는 나중에 끼울 수 있는
sink가 정하며, sink가 없으면 로그로만 남으므로 검수가 sink에 의존하지 않는다.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger(__name__)


class Stage(StrEnum):
    """BE의 AgentStage와 같은 이름. COMPLETED는 여기서가 아니라 BE가 보낸다."""

    BANNED_WORD_CHECK = "BANNED_WORD_CHECK"
    SOCIAL_HISTORICAL_SEARCH = "SOCIAL_HISTORICAL_SEARCH"
    COMPANY_VALUES_SEARCH = "COMPANY_VALUES_SEARCH"
    EXTERNAL_SEARCH = "EXTERNAL_SEARCH"
    FINAL_ASSESSMENT = "FINAL_ASSESSMENT"
    ALTERNATIVE_GENERATION = "ALTERNATIVE_GENERATION"
    OUTPUT_VALIDATION = "OUTPUT_VALIDATION"


class StageStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class StageEvent:
    review_id: str | None
    trace_id: str
    stage: Stage
    status: StageStatus


class EventSink(Protocol):
    def emit(self, event: StageEvent) -> None: ...


class LogSink:
    def emit(self, event: StageEvent) -> None:
        logger.info(
            "stage review_id=%s trace_id=%s stage=%s status=%s",
            event.review_id,
            event.trace_id,
            event.stage,
            event.status,
        )


class StageTracker:
    """단계마다 최신 상태를 기억하고, 바뀔 때마다 sink에 넘긴다.

    sink가 실패해도 검수가 실패하면 안 되므로, 오류는 로그로 남기고 버린다.
    """

    def __init__(self, review_id: str | None, trace_id: str, sink: EventSink) -> None:
        self.review_id, self.trace_id, self.sink = review_id, trace_id, sink
        self.statuses: dict[Stage, StageStatus] = {}

    def emit(self, stage: Stage, status: StageStatus) -> None:
        if self.statuses.get(stage) == status:
            return
        self.statuses[stage] = status
        try:
            self.sink.emit(StageEvent(self.review_id, self.trace_id, stage, status))
        except Exception:
            logger.exception("stage event sink failed trace_id=%s", self.trace_id)

    def skip_unstarted(self, before: Stage) -> None:
        """`before` 앞에서 한 번도 실행되지 않은 단계를 모두 건너뜀으로 표시한다."""
        for stage in Stage:
            if stage == before:
                return
            if stage not in self.statuses:
                self.emit(stage, StageStatus.SKIPPED)

    def fail_running(self) -> list[Stage]:
        """실행 중인 단계를 모두 실패로 표시하고 그 목록을 돌려준다."""
        running = [s for s, st in self.statuses.items() if st == StageStatus.RUNNING]
        for stage in running:
            self.emit(stage, StageStatus.FAILED)
        return running


current_tracker: ContextVar[StageTracker | None] = ContextVar("current_tracker", default=None)
