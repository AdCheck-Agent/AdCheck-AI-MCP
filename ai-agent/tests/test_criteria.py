import json

from app.graph.nodes.review_llm import review_llm
from app.graph.nodes.validate_result import validate_result
from app.llm.client import set_review_model
from app.llm.criteria import CRITERIA, criteria_texts
from tests.test_review_llm import FakeModel, judgment, make_state
from tests.test_validate_result import finding, make


def with_criteria(*ids: str) -> str:
    base = json.loads(judgment())
    base["findings"][0]["criteria_ids"] = list(ids)
    return json.dumps(base, ensure_ascii=False)


def test_criteria_ids_are_unique_and_texts_known() -> None:
    assert len({c.id for c in CRITERIA}) == len(CRITERIA) == 11
    assert criteria_texts(["K1", "K1", "K2"]) == [CRITERIA[0].text, CRITERIA[1].text]


def test_unknown_criteria_ids_are_ignored() -> None:
    assert criteria_texts(["K99", "bogus", "K9"]) == [CRITERIA[8].text]


def test_prompt_lists_criteria_and_result_maps_ids_to_text() -> None:
    model = FakeModel(with_criteria("K1", "K2", "K99"))
    set_review_model(model)
    try:
        result = review_llm(make_state())
    finally:
        set_review_model(None)
    assert "<criteria>" in model.calls[0][1] and "K1" in model.calls[0][1]
    assert result["related_criteria"] == [CRITERIA[0].text, CRITERIA[1].text]


def test_no_criteria_ids_gives_empty_list() -> None:
    set_review_model(FakeModel(judgment()))
    try:
        result = review_llm(make_state())
    finally:
        set_review_model(None)
    assert result["related_criteria"] == []


def test_criteria_dropped_when_finding_quote_not_in_source() -> None:
    bad = json.loads(with_criteria("K1"))
    bad["findings"][0]["quote"] = "원문에 없는 표현"
    set_review_model(FakeModel(json.dumps(bad, ensure_ascii=False)))
    try:
        result = review_llm(make_state())
    finally:
        set_review_model(None)
    assert result["related_criteria"] == []


def test_validator_clears_criteria_on_pass_and_when_no_findings_remain() -> None:
    assert validate_result(make("pass", [], related_criteria=["x"]))["related_criteria"] == []
    update = validate_result(
        make("needs_review", [finding(quote="없는 표현")], related_criteria=["x"])
    )
    assert update["related_criteria"] == []


def test_validator_keeps_criteria_for_valid_revise() -> None:
    assert validate_result(make("revise", [finding()], related_criteria=["x"])) == {}
