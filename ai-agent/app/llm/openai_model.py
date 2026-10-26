import logging
import time

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
# Rate limit and server errors are usually gone a moment later; anything else is not retried.
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_WAIT = 5.0


class OpenAIReviewModel:
    """ReviewModel backed by the OpenAI chat completions API (JSON mode, temperature 0)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: float = 10,
        client: httpx.Client | None = None,
        retry_wait: float = 1.0,
    ) -> None:
        self._model = model
        self._retry_wait = retry_wait
        self._client = client or httpx.Client(timeout=timeout)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def generate(self, system: str, user: str) -> str:
        """One call, retried once after a short wait on a timeout, 429 or 5xx."""
        body = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = self._post(body)
        except httpx.TransportError as exc:
            logger.warning("openai call failed, retrying once error=%s", type(exc).__name__)
            time.sleep(self._retry_wait)
            response = self._post(body)
        else:
            if response.status_code in RETRY_STATUS:
                wait = self._wait(response)
                logger.warning(
                    "openai call failed, retrying once http=%s wait=%.1fs",
                    response.status_code,
                    wait,
                )
                time.sleep(wait)
                response = self._post(body)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _post(self, body: dict) -> httpx.Response:
        return self._client.post(OPENAI_CHAT_URL, headers=self._headers, json=body)

    def _wait(self, response: httpx.Response) -> float:
        """Retry-After when the API gives one, capped so a review does not stall on it."""
        try:
            wait = float(response.headers.get("retry-after", self._retry_wait))
        except ValueError:
            wait = self._retry_wait
        return min(max(wait, 0.0), MAX_RETRY_WAIT)


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
