import asyncio
import logging
from uuid import UUID

import httpx

from business_mcp.config import Settings, get_settings
from business_mcp.schemas import CheckpointLevel, CheckpointResult

logger = logging.getLogger(__name__)


def _failure(response: httpx.Response) -> CheckpointResult:
    """Read the backend's error format; status is judged by HTTP code, then error.code."""
    code = trace_id = None
    retryable = response.status_code >= 500
    try:
        body = response.json()
        error = body.get("error") or {}
        code, trace_id = error.get("code"), body.get("trace_id")
        retryable = bool(error.get("retryable", retryable))
    except (ValueError, AttributeError):
        pass
    logger.warning(
        "checkpoint rejected http=%s code=%s trace_id=%s", response.status_code, code, trace_id
    )
    return CheckpointResult(
        status="error",
        http_status=response.status_code,
        error_code=code,
        trace_id=trace_id,
        retryable=retryable,
        message=f"백엔드가 체크포인트를 거부했습니다 ({response.status_code}).",
    )


async def save_checkpoint(
    original_text_id: str,
    checkpoint_level: CheckpointLevel,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CheckpointResult:
    """Save the review stage on the backend. One attempt, no retry.

    Retrying is left to the caller on purpose: the backend overwrites with whatever it
    receives, so a late retry of an old stage would move the review backwards.
    The internal key is read from settings only; it is never a Tool argument.
    """
    UUID(original_text_id)  # the backend requires a UUID; fail before any network call
    config = settings if settings is not None else get_settings()
    key = config.internal_api_key
    if not config.adcheck_be_base_url or key is None or not key.get_secret_value().strip():
        return CheckpointResult(
            status="unavailable",
            message="ADCHECK_BE_BASE_URL 또는 INTERNAL_API_KEY가 설정되지 않았습니다.",
        )
    url = config.adcheck_be_base_url.rstrip("/") + "/api/v1/reviews/checkpoint"
    try:
        async with asyncio.timeout(config.checkpoint_timeout_seconds):
            async with httpx.AsyncClient(transport=transport, follow_redirects=False) as http:
                response = await http.patch(
                    url,
                    headers={"X-Internal-Key": key.get_secret_value()},
                    json={
                        "original_text_id": original_text_id,
                        "checkpoint_level": checkpoint_level,
                    },
                )
    except TimeoutError:
        return CheckpointResult(
            status="timeout", retryable=True, message="체크포인트 저장 시간이 초과되었습니다."
        )
    except httpx.HTTPError:
        return CheckpointResult(
            status="error", retryable=True, message="백엔드에 연결하지 못했습니다."
        )
    if response.status_code == 200:
        return CheckpointResult(
            status="ok", http_status=200, message="체크포인트가 저장되었습니다."
        )
    return _failure(response)
