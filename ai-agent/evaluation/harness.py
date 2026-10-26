"""Shared runner: builds a graph state from a case and runs it with a given model."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import app.graph.graph as graph_module
from app.graph.state import initial_state
from app.llm.client import ReviewModel, set_review_model
from app.schemas.review import Evidence, ReviewRequest, ReviewResponse

CASES_PATH = Path(__file__).parent / "cases.json"
# Bump when real-model cases are added or their expectations change, so before/after runs compare
# the same set.
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
            # The external search node is async-only, so the graph must run on the async API.
            result = asyncio.run(graph.ainvoke(initial_state(request)))
            return ReviewResponse.model_validate(result)
    finally:
        set_review_model(None)


def missing_quotes(case: dict, response: ReviewResponse) -> list[str]:
    """Expected quotes that no finding points at (a risky phrase the model overlooked)."""
    found = " ".join(f.quote for f in response.findings)
    return [q for q in case.get("expected_quotes", []) if q not in found]
