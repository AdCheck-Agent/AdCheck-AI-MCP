"""Stage progress events: which step of the review is running, done, skipped or failed.

The agent only produces the events. Where they go (a backend API, a stream) is a sink that can
be plugged in later; without one they are just logged, so a review never depends on it.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger(__name__)


class Stage(StrEnum):
    """Same names as the backend's AgentStage. COMPLETED is sent by the backend, not here."""

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
    """Remembers each stage's latest status and hands every change to the sink.

    A sink that fails must never fail the review, so errors are logged and dropped.
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
        """Mark every stage ahead of `before` that never ran as skipped."""
        for stage in Stage:
            if stage == before:
                return
            if stage not in self.statuses:
                self.emit(stage, StageStatus.SKIPPED)

    def fail_running(self) -> None:
        running = [s for s, st in self.statuses.items() if st == StageStatus.RUNNING]
        for stage in running:
            self.emit(stage, StageStatus.FAILED)


current_tracker: ContextVar[StageTracker | None] = ContextVar("current_tracker", default=None)
