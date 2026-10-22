import logging

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIReviewModel:
    """ReviewModel backed by the OpenAI chat completions API (JSON mode, temperature 0)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: float = 10,
        client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._client = client or httpx.Client(timeout=timeout)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def generate(self, system: str, user: str) -> str:
        response = self._client.post(
            OPENAI_CHAT_URL,
            headers=self._headers,
            json={
                "model": self._model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def create_openai_model(settings: Settings) -> OpenAIReviewModel | None:
    """Return a model only when a key is configured; otherwise the mock reviewer stays active."""
    key = settings.openai_api_key
    if key is None or not key.get_secret_value().strip():
        return None
    logger.info("openai review model enabled model=%s", settings.openai_model)
    return OpenAIReviewModel(
        key.get_secret_value().strip(),
        settings.openai_model,
        settings.http_timeout_seconds,
    )
