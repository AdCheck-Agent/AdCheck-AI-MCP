import pytest
from app.core.config import get_settings
from app.llm.client import set_review_model


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch: pytest.MonkeyPatch):
    """Tests never call a real LLM, even if a key exists in the local .env."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    set_review_model(None)
    yield
    set_review_model(None)
    get_settings.cache_clear()
