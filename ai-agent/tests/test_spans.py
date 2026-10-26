import pytest
from app.llm.alternative import _repeats_rest
from app.llm.spans import apply_with_spans, locate_findings
from app.schemas.review import Finding


def finding(quote="위험 문구", **kwargs):
    return Finding(
        category="social_issue",
        severity="medium",
        quote=quote,
        reason="확인 필요",
        needs_human_review=True,
        **kwargs,
    )


def test_repeated_quotes_have_distinct_utf16_offsets():
    items = locate_findings("😀 위험 문구 / 위험 문구", [finding()])
    assert [(f.start_offset, f.end_offset) for f in items] == [(3, 8), (11, 16)]
    assert all(f.detection_type == "SEMANTIC" and f.needs_human_review for f in items)


def test_only_the_selected_occurrence_changes():
    item = finding(suggestion="새 표현", start_offset=11, end_offset=16)
    assert apply_with_spans("😀 위험 문구 / 위험 문구", [item]) == (
        "😀 위험 문구 / 새 표현",
        [("새 표현", 11, 15)],
    )


def test_alternative_validation_removes_the_selected_occurrence_from_context():
    source = "봄 위험 문구 특가, 위험 문구 상품"
    item = locate_findings(source, [finding()])[1]
    # 첫 번째 위치를 지우면 나머지에 "봄 특가"가 잘못 생긴다.
    assert _repeats_rest(source, item, "봄 특가") == set()
    assert _repeats_rest(source, item, "봄 위험 문구 특가") == {"봄 위험 문구 특가"}


def test_legacy_quote_changes_every_occurrence_and_tracks_new_positions():
    applied = apply_with_spans("위험 문구 / 위험 문구", [finding(suggestion="새")])
    assert applied == ("새 / 새", [("새", 0, 1), ("새", 4, 5)])


def test_original_whitespace_is_retained_in_the_quote():
    items = locate_findings("위험\n  문구", [finding()])
    assert items[0].quote == "위험\n  문구"
    assert (items[0].start_offset, items[0].end_offset) == (0, 7)


def test_same_span_same_alternative_applies_once():
    one = finding(suggestion="새 문구")
    two = one.model_copy(update={"reason": "다른 이유"})
    assert apply_with_spans("위험 문구", [one, two])[0] == "새 문구"


def test_same_span_with_different_review_details_is_preserved():
    one = finding()
    two = one.model_copy(update={"severity": "high", "needs_human_review": False})
    items = locate_findings("위험 문구", [one, two, one])
    assert len(items) == 2
    assert [item.severity for item in items] == ["medium", "high"]
    assert [item.needs_human_review for item in items] == [True, False]


@pytest.mark.parametrize(
    "other", [finding(suggestion="다른 대안"), finding("문구", suggestion="대안")]
)
def test_conflicting_alternatives_are_not_silently_applied(other):
    assert apply_with_spans("위험 문구", [finding(suggestion="새 문구"), other]) is None


def test_invalid_explicit_offset_does_not_fall_back_to_first_occurrence():
    assert locate_findings("위험 문구 / 위험 문구", [finding(start_offset=1, end_offset=6)]) == []


@pytest.mark.parametrize(
    "source,quote", [("ＡＢＣ", "abc"), ("e\u0301", "é"), ("\u1100\u1161", "가")]
)
def test_normalized_quotes_still_point_to_the_exact_original(source, quote):
    items = locate_findings("😀 " + source, [finding(quote)])
    assert items[0].quote == source
    assert (items[0].start_offset, items[0].end_offset) == (3, 3 + len(source))
