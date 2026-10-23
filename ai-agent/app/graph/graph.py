import inspect
from collections.abc import Callable
from functools import partial
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.clients.business_mcp_client import BusinessTools
from app.clients.rag_mcp_client import RagTools
from app.events import Stage, StageStatus, StageTracker, current_tracker
from app.graph.nodes.decide_result import mark_needs_review, mark_pass
from app.graph.nodes.generate_alternative import generate_alternative
from app.graph.nodes.retrieve_corporate_value import (
    retrieve_corporate_value,
    retrieve_corporate_value_live,
)
from app.graph.nodes.retrieve_external_evidence import retrieve_external_evidence
from app.graph.nodes.retrieve_social_context import (
    retrieve_social_context,
    retrieve_social_context_live,
)
from app.graph.nodes.review_llm import review_llm
from app.graph.nodes.rule_filter import rule_filter
from app.graph.nodes.validate_result import validate_result
from app.graph.state import ReviewState


def route_result(
    state: ReviewState,
) -> Literal["revise", "pass", "needs_review", "external_search"]:
    if any(code.endswith("_FAILED") for code in state["rag_errors"]):
        return "needs_review"

    query = state["external_search_query"]
    if (
        not state["evidence_sufficient"]
        and not state["external_search_attempted"]
        and query
        and 0 < len(query.strip()) <= 400
    ):
        return "external_search"

    if not state["evidence_sufficient"] or state["risk"] == "uncertain":
        return "needs_review"

    return "revise" if state["risk"] == "yes" else "pass"


def tracked(
    stage: Stage,
    node: Callable[..., Any],
    *,
    skip_when: Callable[[ReviewState], bool] | None = None,
    keep_running: Callable[[ReviewState, dict], bool] | None = None,
) -> Callable[[ReviewState], Any]:
    """Wrap a node so its progress is reported; behaves exactly like the node otherwise.

    The wrapper is sync for a sync node and async for an async node, so the graph keeps
    running both ways it already did.

    skip_when: the node has nothing to do (reported as SKIPPED, the node still runs).
    keep_running: the stage is not finished yet after this run (e.g. it will loop back).
    """

    def before(state: ReviewState) -> tuple[StageTracker | None, bool]:
        tracker = current_tracker.get()
        skipped = bool(skip_when and skip_when(state))
        if tracker:
            if stage == Stage.OUTPUT_VALIDATION:
                tracker.skip_unstarted(stage)
            tracker.emit(stage, StageStatus.SKIPPED if skipped else StageStatus.RUNNING)
        return tracker, skipped

    def after(
        tracker: StageTracker | None, skipped: bool, state: ReviewState, update: dict
    ) -> None:
        if tracker and not skipped and not (keep_running and keep_running(state, update)):
            tracker.emit(stage, StageStatus.SUCCEEDED)

    if inspect.iscoroutinefunction(node):

        async def run_async(state: ReviewState) -> dict:
            tracker, skipped = before(state)
            try:
                update = await node(state)
            except Exception:
                if tracker:
                    tracker.emit(stage, StageStatus.FAILED)
                raise
            after(tracker, skipped, state, update)
            return update

        return run_async

    def run(state: ReviewState) -> dict:
        tracker, skipped = before(state)
        try:
            update = node(state)
        except Exception:
            if tracker:
                tracker.emit(stage, StageStatus.FAILED)
            raise
        after(tracker, skipped, state, update)
        return update

    return run


def build_graph(
    business_tools: BusinessTools | None = None,
    rag_tools: RagTools | None = None,
) -> CompiledStateGraph:
    graph = StateGraph(ReviewState)

    graph.add_node("rule_filter", tracked(Stage.BANNED_WORD_CHECK, rule_filter))
    graph.add_node(
        "retrieve_social_context",
        tracked(
            Stage.SOCIAL_HISTORICAL_SEARCH,
            partial(retrieve_social_context_live, tools=rag_tools)
            if rag_tools
            else retrieve_social_context,
        ),
    )
    graph.add_node(
        "retrieve_corporate_value",
        tracked(
            Stage.COMPANY_VALUES_SEARCH,
            partial(retrieve_corporate_value_live, tools=rag_tools)
            if rag_tools
            else retrieve_corporate_value,
            skip_when=lambda state: not state["context"].company_id,
        ),
    )
    graph.add_node(
        "review_llm",
        tracked(
            Stage.FINAL_ASSESSMENT,
            review_llm,
            # An evidence gap sends the run through external search and back to this node.
            keep_running=lambda state, update: (
                route_result({**state, **update}) == "external_search"
            ),
        ),
    )
    graph.add_node(
        "external_search",
        tracked(Stage.EXTERNAL_SEARCH, partial(retrieve_external_evidence, tools=business_tools)),
    )
    graph.add_node(
        "generate_alternative", tracked(Stage.ALTERNATIVE_GENERATION, generate_alternative)
    )
    graph.add_node("mark_pass", mark_pass)
    graph.add_node("mark_needs_review", mark_needs_review)
    graph.add_node("validate_result", tracked(Stage.OUTPUT_VALIDATION, validate_result))

    graph.add_edge(START, "rule_filter")
    graph.add_edge("rule_filter", "retrieve_social_context")
    graph.add_edge("retrieve_social_context", "retrieve_corporate_value")
    graph.add_edge("retrieve_corporate_value", "review_llm")

    graph.add_conditional_edges(
        "review_llm",
        route_result,
        {
            "revise": "generate_alternative",
            "pass": "mark_pass",
            "needs_review": "mark_needs_review",
            "external_search": "external_search",
        },
    )

    # Search outcome is input to the final judgment, never a verdict by itself.
    graph.add_edge("external_search", "review_llm")

    for node in ("generate_alternative", "mark_pass", "mark_needs_review"):
        graph.add_edge(node, "validate_result")

    graph.add_edge("validate_result", END)

    return graph.compile()
