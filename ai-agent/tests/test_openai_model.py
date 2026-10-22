import json

import httpx
import pytest
from app.core.config import Settings
from app.llm.openai_model import OpenAIReviewModel, create_openai_model


def make_model(handler) -> OpenAIReviewModel:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAIReviewModel("sk-test", "gpt-4o-mini", client=client)


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


def test_no_model_without_key() -> None:
    assert create_openai_model(Settings(_env_file=None, openai_api_key=None)) is None
    assert create_openai_model(Settings(_env_file=None, openai_api_key="  ")) is None


def test_model_created_with_key() -> None:
    settings = Settings(_env_file=None, openai_api_key="sk-test", openai_model="gpt-4o-mini")
    assert isinstance(create_openai_model(settings), OpenAIReviewModel)
