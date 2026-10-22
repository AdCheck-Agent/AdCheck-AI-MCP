import json

import pytest
from rag_mcp.evaluation import CASES, evaluate, first_hit_rank, score_case, summarize
from rag_mcp.schemas import RetrievedEvidence


def evidence(rule_id: str, score: float, company_id: str | None = None) -> RetrievedEvidence:
    return RetrievedEvidence(
        document="doc",
        section="section",
        snippet="snippet",
        rule_id=rule_id,
        version="v1",
        document_id="doc",
        chunk_id=f"{rule_id}:0",
        company_id=company_id,
        document_type="ethics_policy",
        record_type="uploaded_company_document",
        score=score,
    )


def case(**overrides) -> dict:
    return {
        "id": "C-1",
        "corpus": "social",
        "company_id": None,
        "query": "q",
        "expected_any_rule_ids": ["R2"],
        "must_not_return_rule_ids": [],
    } | overrides


def test_first_hit_rank_uses_first_expected_chunk():
    assert first_hit_rank(["R1", "R2", "R2"], ["R2", "R3"]) == 2
    assert first_hit_rank(["R1"], ["R2"]) is None
    assert first_hit_rank([], []) is None


def test_score_case_flags_other_company_and_forbidden_ids():
    row = score_case(
        case(
            corpus="corporate_demo",
            company_id="a",
            expected_any_rule_ids=["a-1"],
            must_not_return_rule_ids=["x-9"],
        ),
        [evidence("a-1", 0.8, "a"), evidence("b-1", 0.5, "b"), evidence("x-9", 0.4, "a")],
        3.0,
    )
    assert row["hit_rank"] == 1 and row["hit_score"] == 0.8
    assert row["isolation_violations"] == ["b-1", "x-9"]


def test_summarize_separates_retrieval_negative_and_isolation():
    results = [
        score_case(case(id="P1"), [evidence("R2", 0.7)], 10),
        score_case(case(id="P2"), [evidence("R1", 0.6), evidence("R2", 0.5)], 20),
        score_case(case(id="P3"), [evidence("R1", 0.6)], 30),
        score_case(
            case(id="N1", kind="negative", expected_any_rule_ids=[]), [evidence("R1", 0.3)], 40
        ),
        score_case(
            case(id="I1", corpus="corporate_demo", company_id="z", expected_any_rule_ids=[]),
            [],
            5,
        ),
    ]
    summary = summarize(results, top_k=5)
    overall = summary["retrieval"]["all"]
    assert overall["cases"] == 3
    assert overall["hit@1"] == pytest.approx(1 / 3, abs=1e-4)
    assert overall["hit@5"] == pytest.approx(2 / 3, abs=1e-4)
    assert overall["mrr"] == pytest.approx(0.5, abs=1e-4)
    assert overall["misses"] == ["P3"]
    assert summary["scores"]["negative_top_score_max"] == 0.3
    assert summary["scores"]["hit_score_min"] == 0.5
    assert summary["isolation_cases_returning_results"] == []
    assert summary["latency_ms"]["max"] == 40


async def test_evaluate_routes_corpus_and_company():
    calls = []

    class Store:
        async def search(self, query, **kwargs):
            calls.append(kwargs)
            return []

    await evaluate(Store(), [case(), case(corpus="corporate_demo", company_id="a")])
    assert calls[0]["collection"] == "social" and calls[0]["company_id"] is None
    assert calls[1] == calls[1] | {"collection": "corporate", "company_id": "a"}


def test_fixture_cases_are_well_formed():
    cases = json.loads(CASES.read_text("utf-8"))["cases"]
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["corpus"] in ("social", "corporate_demo")
        assert (c["company_id"] is None) == (c["corpus"] == "social")
        if c.get("kind") == "negative":
            assert not c["expected_any_rule_ids"]
