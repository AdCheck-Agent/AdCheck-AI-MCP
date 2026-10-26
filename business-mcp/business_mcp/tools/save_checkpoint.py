import asyncio
import logging
from uuid import UUID

import httpx

from business_mcp.config import Settings, get_settings
from business_mcp.schemas import CheckpointError, CheckpointLevel, CheckpointResult

logger = logging.getLogger(__name__)


def _failure(response: httpx.Response) -> CheckpointResult:
    """BE의 오류 형식을 읽는다. 상태는 HTTP 코드로, 그다음 error.code로 판단한다."""
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
    *,
    result: dict | None = None,
    error: CheckpointError | None = None,
) -> CheckpointResult:
    """검수 단계를 BE에 저장한다. 한 번만 보내고 재시도하지 않는다.

    재시도는 일부러 호출하는 쪽에 맡긴다. BE는 받은 값으로 덮어쓰므로,
    이전 단계를 늦게 재시도하면 검수가 뒤로 돌아간다.
    내부 키는 설정에서만 읽으며, 절대 Tool 인자로 받지 않는다.
    """
    UUID(original_text_id)  # BE는 UUID를 요구한다. 네트워크 호출 전에 실패시킨다
    if result is not None and checkpoint_level != "COMPLETED":
        raise ValueError("result는 COMPLETED CP에만 포함할 수 있습니다.")
    if (error is not None) != (checkpoint_level == "FAILED"):
        raise ValueError("error는 FAILED CP에 반드시, FAILED CP에만 포함합니다.")
    config = settings if settings is not None else get_settings()
    key = config.internal_api_key
    if not config.adcheck_be_base_url or key is None or not key.get_secret_value().strip():
        return CheckpointResult(
            status="unavailable",
            message="ADCHECK_BE_BASE_URL 또는 INTERNAL_API_KEY가 설정되지 않았습니다.",
        )
    url = config.adcheck_be_base_url.rstrip("/") + "/api/v1/reviews/checkpoint"
    payload = {"original_text_id": original_text_id, "checkpoint_level": checkpoint_level}
    if result is not None:
        payload["result"] = result
    if error is not None:
        payload["error"] = error.model_dump(mode="json")
    try:
        async with asyncio.timeout(config.checkpoint_timeout_seconds):
            async with httpx.AsyncClient(transport=transport, follow_redirects=False) as http:
                response = await http.patch(
                    url,
                    headers={"X-Internal-Key": key.get_secret_value()},
                    json=payload,
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
