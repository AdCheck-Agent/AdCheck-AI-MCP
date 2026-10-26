import json

import httpx
import pytest
from business_mcp.config import Settings
from business_mcp.schemas import CheckpointError, CheckpointResult
from business_mcp.tools.save_checkpoint import save_checkpoint

ID = "550e8400-e29b-41d4-a716-446655440000"
TRACE = "trace_0123456789abcdef0123456789abcdef"


def settings(**extra) -> Settings:
    base = {"adcheck_be_base_url": "http://be:8080/", "internal_api_key": "secret-key"}
    return Settings(_env_file=None, **{**base, **extra})


async def test_wire_contract_and_key_in_header() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": "체크포인트가 저장되었습니다."})

    result = await save_checkpoint(ID, "FINAL_ASSESSMENT", settings(), httpx.MockTransport(handler))
    request = seen[0]
    assert result.status == "ok" and result.http_status == 200
    assert request.method == "PATCH"
    assert str(request.url) == "http://be:8080/api/v1/reviews/checkpoint"
    assert request.headers["x-internal-key"] == "secret-key"
    assert json.loads(request.content) == {
        "original_text_id": ID,
        "checkpoint_level": "FINAL_ASSESSMENT",
    }


@pytest.mark.parametrize(
    ("status", "code"),
    [(400, "VALIDATION_ERROR"), (401, "UNAUTHORIZED"), (404, "REVIEW_NOT_FOUND")],
)
async def test_backend_error_is_kept_and_not_retried(status: int, code: str) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        body = {"error": {"code": code, "message": "m", "retryable": False}, "trace_id": "t1"}
        return httpx.Response(status, json=body)

    result = await save_checkpoint(ID, "COMPLETED", settings(), httpx.MockTransport(handler))
    assert (result.status, result.http_status, result.error_code) == ("error", status, code)
    assert result.trace_id == "t1" and result.retryable is False
    assert len(calls) == 1
    assert "secret-key" not in result.model_dump_json()


async def test_server_error_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    result = await save_checkpoint(ID, "COMPLETED", settings(), httpx.MockTransport(handler))
    assert result.status == "error" and result.retryable is True


async def test_network_error_and_timeout() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    result = await save_checkpoint(ID, "COMPLETED", settings(), httpx.MockTransport(down))
    assert result.status == "error" and result.retryable is True

    async def slow(request: httpx.Request) -> httpx.Response:
        import asyncio

        await asyncio.sleep(1)
        return httpx.Response(200)

    result = await save_checkpoint(
        ID, "COMPLETED", settings(checkpoint_timeout_seconds=0.05), httpx.MockTransport(slow)
    )
    assert result.status == "timeout"


async def test_missing_config_makes_no_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call")

    for cfg in (
        Settings(_env_file=None),
        settings(internal_api_key=None),
        settings(adcheck_be_base_url=None),
    ):
        result = await save_checkpoint(ID, "COMPLETED", cfg, httpx.MockTransport(handler))
        assert result.status == "unavailable"


async def test_non_uuid_rejected_before_call() -> None:
    with pytest.raises(ValueError):
        await save_checkpoint("not-a-uuid", "COMPLETED", settings())


async def test_mcp_tool_validates_arguments() -> None:
    from test_mcp_transport import mcp_session

    async with mcp_session(Settings(_env_file=None)) as session:
        bad_level = await session.call_tool(
            "save_checkpoint", {"original_text_id": ID, "checkpoint_level": "banned_word_check"}
        )
        bad_id = await session.call_tool(
            "save_checkpoint", {"original_text_id": "x", "checkpoint_level": "COMPLETED"}
        )
        unconfigured = await session.call_tool(
            "save_checkpoint", {"original_text_id": ID, "checkpoint_level": "COMPLETED"}
        )
    assert bad_level.isError is True
    assert bad_id.isError is True
    assert CheckpointResult.model_validate(unconfigured.structuredContent).status == "unavailable"
    assert unconfigured.isError is True


async def test_failed_cp_sends_the_error() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": "ok"})

    error = CheckpointError(
        code="REVIEW_TIMEOUT", message="시간 초과", stage="FINAL_ASSESSMENT", trace_id=TRACE
    )
    result = await save_checkpoint(
        ID, "FAILED", settings(), httpx.MockTransport(handler), error=error
    )
    assert result.status == "ok"
    assert seen == [
        {
            "original_text_id": ID,
            "checkpoint_level": "FAILED",
            "error": {
                "code": "REVIEW_TIMEOUT",
                "message": "시간 초과",
                "stage": "FINAL_ASSESSMENT",
                "trace_id": TRACE,
            },
        }
    ]


@pytest.mark.parametrize(
    ("level", "error"),
    [
        ("FAILED", None),
        ("COMPLETED", CheckpointError(code="REVIEW_ERROR", message="m", trace_id=TRACE)),
        ("FINAL_ASSESSMENT", CheckpointError(code="REVIEW_ERROR", message="m", trace_id=TRACE)),
    ],
)
async def test_error_only_and_always_with_failed(level: str, error) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must fail before any network call")

    with pytest.raises(ValueError):
        await save_checkpoint(ID, level, settings(), httpx.MockTransport(handler), error=error)
