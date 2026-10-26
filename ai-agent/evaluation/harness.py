"""공용 실행기: 케이스로 그래프 상태를 만들고 주어진 모델로 실행한다."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import app.graph.graph as graph_module
from app.graph.state import initial_state
from app.llm.client import ReviewModel, set_review_model
from app.schemas.review import Evidence, ReviewRequest, ReviewResponse

CASES_PATH = Path(__file__).parent / "cases.json"
# 실제 모델용 케이스를 더하거나 기대값을 바꾸면 올린다. 그래야 개선 전후가
# 같은 평가셋으로 비교된다.
EVAL_SET_VERSION = "v5"


def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _evidence(case: dict, source: str) -> list[Evidence]:
    return [
        Evidence(**{k: v for k, v in item.items() if k != "source"})
        for item in case["evidence"]
        if item["source"] == source
    ]


def run_case(case: dict, model: ReviewModel | None) -> ReviewResponse:
    context = {"channel": "sns"}
    if case.get("company_id"):
        context["company_id"] = case["company_id"]
    request = ReviewRequest(text=case["text"], context=context)
    social, corporate = _evidence(case, "social"), _evidence(case, "corporate")
    set_review_model(model)
    try:
        with (
            patch.object(
                graph_module,
                "retrieve_social_context",
                lambda s: {"social_context_evidence": social},
            ),
            patch.object(
                graph_module,
                "retrieve_corporate_value",
                lambda s: {"corporate_value_evidence": corporate},
            ),
        ):
            graph = graph_module.build_graph()
            # 외부 검색 노드는 비동기 전용이므로 그래프를 비동기 API로 실행해야 한다.
            result = asyncio.run(graph.ainvoke(initial_state(request)))
            return ReviewResponse.model_validate(result)
    finally:
        set_review_model(None)


def missing_quotes(case: dict, response: ReviewResponse) -> list[str]:
    """어떤 지적도 가리키지 않은 기대 인용 (모델이 놓친 위험 표현)."""
    found = " ".join(f.quote for f in response.findings)
    return [q for q in case.get("expected_quotes", []) if q not in found]
