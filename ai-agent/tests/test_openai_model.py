import json

import httpx
import pytest
from app.core.config import Settings
from app.llm.openai_model import OpenAIReviewModel, create_openai_model


def make_model(handler) -> OpenAIReviewModel:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAIReviewModel("sk-test", "gpt-4o-mini", client=client, retry_wait=0)


def ok(content: str = '{"ok": true}') -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def sequence(*responses):
    """응답을 순서대로 돌려주는 핸들러(예외면 발생시킴). 호출을 기록한다."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        item = responses[len(calls)]
        calls.append(request)
        if isinstance(item, Exception):
            raise item
        return item

    return handler, calls


def test_generate_sends_json_mode_request_and_returns_content() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    assert make_model(handler).generate("시스템", "사용자") == '{"ok": true}'
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "gpt-4o-mini"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["temperature"] == 0
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]


def test_http_error_is_raised_for_the_judge_to_handle() -> None:
    model = make_model(lambda request: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        model.generate("s", "u")


@pytest.mark.parametrize("status", [429, 500, 503])
def test_rate_limit_or_server_error_is_retried_once(status: int) -> None:
    handler, calls = sequence(httpx.Response(status), ok())
    assert make_model(handler).generate("s", "u") == '{"ok": true}'
    assert len(calls) == 2


def test_timeout_is_retried_once() -> None:
    handler, calls = sequence(httpx.ReadTimeout("slow"), ok())
    assert make_model(handler).generate("s", "u") == '{"ok": true}'
    assert len(calls) == 2


def test_second_failure_is_raised() -> None:
    handler, calls = sequence(httpx.Response(503), httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        make_model(handler).generate("s", "u")
    assert len(calls) == 2
    handler, calls = sequence(httpx.ConnectError("down"), httpx.ConnectError("down"))
    with pytest.raises(httpx.ConnectError):
        make_model(handler).generate("s", "u")
    assert len(calls) == 2


@pytest.mark.parametrize("status", [400, 401, 404])
def test_request_errors_are_not_retried(status: int) -> None:
    handler, calls = sequence(httpx.Response(status))
    with pytest.raises(httpx.HTTPStatusError):
        make_model(handler).generate("s", "u")
    assert len(calls) == 1


def test_retry_after_is_honoured_but_capped() -> None:
    model = make_model(lambda request: ok())
    assert model._wait(httpx.Response(429, headers={"retry-after": "2"})) == 2
    assert model._wait(httpx.Response(429, headers={"retry-after": "120"})) == 5
    assert model._wait(httpx.Response(429, headers={"retry-after": "soon"})) == 0
    assert model._wait(httpx.Response(429)) == 0


def test_no_model_without_key() -> None:
    assert create_openai_model(Settings(_env_file=None, openai_api_key=None)) is None
    assert create_openai_model(Settings(_env_file=None, openai_api_key="  ")) is None


def test_model_created_with_key() -> None:
    settings = Settings(_env_file=None, openai_api_key="sk-test", openai_model="gpt-4o-mini")
    assert isinstance(create_openai_model(settings), OpenAIReviewModel)
