"""Send "this stage is finished" to the backend, through the Business MCP save_checkpoint Tool.

Why a queue: the backend simply overwrites the stage with whatever it receives, so the calls
for one review must arrive in order and a late old one must never overtake a newer one.
One worker sends them one by one. Nodes only drop an event in the queue and never wait, so a
slow or broken backend cannot slow down or fail a review.
"""

import asyncio
import logging

from app.clients.business_mcp_client import CheckpointResult, CheckpointTools
from app.events import StageEvent, StageStatus

logger = logging.getLogger(__name__)

COMPLETED = "COMPLETED"
_STOP = object()


class CheckpointSink:
    """EventSink that saves a checkpoint each time a stage SUCCEEDS.

    Skipped and failed stages are not saved: nothing was finished there, and a failed review
    is reported by the HTTP error instead.
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

    def complete(self) -> None:
        self._put(COMPLETED)

    def _put(self, level: str) -> None:
        if self.worker is None:
            return
        # Nodes can run in worker threads, so hand over to the event loop thread-safely.
        self.loop.call_soon_threadsafe(self.queue.put_nowait, level)

    async def close(self, timeout: float = 5) -> None:
        """Wait (briefly) until everything queued has been sent."""
        if self.worker is None:
            return
        self.loop.call_soon_threadsafe(self.queue.put_nowait, _STOP)
        try:
            await asyncio.wait_for(asyncio.shield(self.worker), timeout)
        except TimeoutError:
            self.worker.cancel()
            logger.warning("checkpoint flush timed out trace_id=%s", self.trace_id)

    async def _run(self) -> None:
        while (level := await self.queue.get()) is not _STOP:
            await self._send(level)

    async def _send(self, level: str) -> None:
        assert self.original_text_id is not None
        # A retryable failure is retried once, here, before the next stage is sent.
        for attempt in (1, 2):
            try:
                result = await self.tools.save_checkpoint(self.original_text_id, level)
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
