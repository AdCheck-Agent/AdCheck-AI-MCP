"""Business MCP의 save_checkpoint Tool로 BE에 "이 단계가 끝났다"를 보낸다.

큐를 쓰는 이유: BE는 받은 단계로 그대로 덮어쓰므로, 한 검수의 호출은
순서대로 도착해야 하고 늦게 온 이전 호출이 새 호출을 앞지르면 안 된다.
워커 하나가 하나씩 보낸다. 노드는 이벤트를 큐에 넣기만 하고 기다리지 않으므로,
BE가 느리거나 고장 나도 검수가 늦어지거나 실패하지 않는다.
"""

import asyncio
import logging

from app.clients.business_mcp_client import CheckpointResult, CheckpointTools
from app.events import Stage, StageEvent, StageStatus
from app.schemas.review import ReviewResponse

logger = logging.getLogger(__name__)

COMPLETED = "COMPLETED"
FAILED = "FAILED"
_STOP = object()


class CheckpointSink:
    """단계가 성공할 때마다 체크포인트를 저장하는 EventSink.

    건너뛴 단계와 실패한 단계는 저장하지 않는다. 검증을 마친 검수만 최종 결과와 함께
    COMPLETED를 보내므로, needs_review 판정도 BE 작업을 끝낸다.
    시간 초과나 예외로 끝난 검수는 대신 FAILED를 보내 BE 작업을 끝낸다.
    """

    def __init__(
        self,
        tools: CheckpointTools,
        original_text_id: str | None,
        trace_id: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.tools, self.original_text_id, self.trace_id = tools, original_text_id, trace_id
        self.loop = loop
        self.queue: asyncio.Queue = asyncio.Queue()
        self.worker = loop.create_task(self._run()) if original_text_id else None

    def emit(self, event: StageEvent) -> None:
        if event.status == StageStatus.SUCCEEDED:
            self._put(event.stage.value)

    def complete(self, result: ReviewResponse | None = None) -> None:
        self._put(COMPLETED, {"result": result.model_dump(mode="json")} if result else {})

    def fail(self, code: str, message: str, stage: Stage | None = None) -> None:
        error = {
            "code": code,
            "message": message,
            "stage": stage.value if stage else None,
            "trace_id": self.trace_id,
        }
        self._put(FAILED, {"error": error})

    def _put(self, level: str, extra: dict | None = None) -> None:
        if self.worker is None:
            return
        # 노드는 워커 스레드에서 돌 수 있으므로 이벤트 루프에 스레드 안전하게 넘긴다.
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (level, extra or {}))

    async def close(self, timeout: float = 5) -> None:
        """큐에 쌓인 것을 모두 보낼 때까지 (잠깐) 기다린다."""
        if self.worker is None:
            return
        self.loop.call_soon_threadsafe(self.queue.put_nowait, _STOP)
        try:
            await asyncio.wait_for(asyncio.shield(self.worker), timeout)
        except TimeoutError:
            self.worker.cancel()
            logger.warning("checkpoint flush timed out trace_id=%s", self.trace_id)

    async def _run(self) -> None:
        while (item := await self.queue.get()) is not _STOP:
            await self._send(*item)

    async def _send(self, level: str, extra: dict) -> None:
        assert self.original_text_id is not None
        # 재시도할 수 있는 실패는 다음 단계를 보내기 전에 여기서 한 번 재시도한다.
        for attempt in (1, 2):
            try:
                result = await self.tools.save_checkpoint(self.original_text_id, level, **extra)
            except Exception:
                logger.exception(
                    "checkpoint call failed trace_id=%s level=%s", self.trace_id, level
                )
                result = CheckpointResult(status="error", retryable=True, message="call failed")
            if result.status == "ok":
                return
            logger.warning(
                "checkpoint not saved trace_id=%s level=%s status=%s http=%s code=%s",
                self.trace_id,
                level,
                result.status,
                result.http_status,
                result.error_code,
            )
            if not result.retryable or attempt == 2:
                return
