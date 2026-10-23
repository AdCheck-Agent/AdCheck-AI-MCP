"""Review criteria shown to the user as chips ("관련 검수 기준").

One source of truth for the chip wording. Each criterion points at the RAG criteria document
(`rule_id`) it was written from, so the wording can later come from the search service instead.
The model only picks ids from this list; code maps them back to text and drops anything else.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    id: str
    rule_id: str
    text: str


CRITERIA: tuple[Criterion, ...] = (
    Criterion("K1", "RULE-HIST-001", "역사적 사건·기념일의 상업적 연상 활용"),
    Criterion("K2", "RULE-HIST-001", "사회적 피해와 기억의 가벼운 소비 방지"),
    Criterion("K3", "RULE-CHILD-001", "아동의 성적 대상화 방지"),
    Criterion("K4", "RULE-CHILD-001", "보호자 수치심을 이용한 구매 압박 방지"),
    Criterion("K5", "RULE-DISC-001", "성역할 고정관념 강화 방지"),
    Criterion("K6", "RULE-DISC-001", "인물을 구경거리·평가 대상으로 축소하는 표현 방지"),
    Criterion("K7", "RULE-DIGNITY-001", "취약성·직업·장애 등을 이용한 조롱 방지"),
    Criterion("K8", "RULE-DIGNITY-001", "공포·죄책감을 이용한 구매 유도 방지"),
    Criterion("K9", "RULE-LABOR-001", "과로·위험노동 미화 방지"),
    Criterion("K10", "RULE-LABOR-001", "윤리적 생산 주장의 근거 범위 확인"),
)

_BY_ID = {c.id: c for c in CRITERIA}


def criteria_for_prompt() -> list[dict[str, str]]:
    return [{"id": c.id, "criterion": c.text} for c in CRITERIA]


def criteria_texts(ids: list[str]) -> list[str]:
    """Chip wording for known ids, in first-seen order. Unknown ids are ignored."""
    return [_BY_ID[i].text for i in dict.fromkeys(ids) if i in _BY_ID]
