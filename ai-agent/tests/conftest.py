import pytest
from app.core.config import get_settings
from app.llm.client import set_review_model


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch: pytest.MonkeyPatch):
    """로컬 .env에 키가 있어도 테스트는 실제 LLM을 호출하지 않는다."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    set_review_model(None)
    yield
    set_review_model(None)
    get_settings.cache_clear()
