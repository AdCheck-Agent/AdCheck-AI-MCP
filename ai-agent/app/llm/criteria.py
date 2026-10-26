"""사용자에게 칩으로 보여 줄 검수 기준("관련 검수 기준").

칩 문구의 단일 출처다. 기준마다 바탕이 된 RAG 기준 문서(`rule_id`)를 가리키므로,
나중에는 문구를 검색 서비스에서 가져올 수 있다.
모델은 이 목록에서 id만 고르고, 코드가 id를 문구로 바꾸며 나머지는 버린다.
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
    # 고정된 RAG 기준 파일이 아니라 이번 검수에 첨부된 기업 문서를 가리킨다.
    Criterion("K11", "COMPANY_VALUES", "기업이 밝힌 가치·브랜드 원칙과의 충돌"),
)

_BY_ID = {c.id: c for c in CRITERIA}


def criteria_for_prompt() -> list[dict[str, str]]:
    return [{"id": c.id, "criterion": c.text} for c in CRITERIA]


def criteria_texts(ids: list[str]) -> list[str]:
    """알려진 id의 칩 문구를 처음 나온 순서대로. 모르는 id는 무시한다."""
    return [_BY_ID[i].text for i in dict.fromkeys(ids) if i in _BY_ID]
