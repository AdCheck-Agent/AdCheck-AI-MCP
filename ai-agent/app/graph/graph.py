from functools import partial
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.clients.business_mcp_client import BusinessTools
from app.clients.rag_mcp_client import RagTools
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


def build_graph(
    business_tools: BusinessTools | None = None, rag_tools: RagTools | None = None
) -> CompiledStateGraph:
    graph = StateGraph(ReviewState)
    graph.add_node("rule_filter", rule_filter)
    graph.add_node(
        "retrieve_social_context",
        partial(retrieve_social_context_live, tools=rag_tools)
        if rag_tools
        else retrieve_social_context,
    )
    graph.add_node(
        "retrieve_corporate_value",
        partial(retrieve_corporate_value_live, tools=rag_tools)
        if rag_tools
        else retrieve_corporate_value,
    )
    graph.add_node("review_llm", review_llm)
    graph.add_node("external_search", partial(retrieve_external_evidence, tools=business_tools))
    graph.add_node("generate_alternative", generate_alternative)
    graph.add_node("mark_pass", mark_pass)
    graph.add_node("mark_needs_review", mark_needs_review)
    graph.add_node("validate_result", validate_result)
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
