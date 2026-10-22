from app.graph.nodes.rule_filter import find_rule_hits


def test_banned_expression() -> None:
    hits = find_rule_hits("이 제품을 안 쓰면 정상적인 사람이 아닙니다.")
    assert len(hits) == 1
    assert hits[0].severity == "high"


def test_general_text() -> None:
    assert find_rule_hits("봄맞이 기간 한정 이벤트를 진행합니다.") == []


def test_normalization() -> None:
    assert find_rule_hits("정상적인\n  사람이\t아닙니다")


def test_disabled_rule() -> None:
    assert find_rule_hits("비활성 예시") == []
