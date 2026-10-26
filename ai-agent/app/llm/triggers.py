"""신고된 사례의 결합 조건.

신고된 사례(스타벅스 탱크데이, 무신사 양말 광고 등)는 단어 하나가 아니라
날짜와 문구의 *결합* 때문에 논란이 됐다. 단어 하나만 겹치는 검색 결과나
모델 판정("탱크톱", "5월 18일 새 텀블러")은 일치로 보지 않는다.
`app/rules/case_triggers.json`에 사례 rule_id별로 인정하는 결합을 적고,
목록에 없는 사례는 거르지 않는다.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from app.graph.nodes.rule_filter import normalize
from app.llm.dates import date_keys, number_date_keys

TRIGGERS_PATH = Path(__file__).resolve().parents[1] / "rules" / "case_triggers.json"


@lru_cache
def load_triggers(path: Path = TRIGGERS_PATH) -> dict[str, list[list[str]]]:
    data = json.loads(path.read_text("utf-8"))
    return {
        rule_id: [list(group) for group in body["any_of"]]
        for rule_id, body in data.items()
        if isinstance(body, dict) and body.get("any_of")
    }


def _squash(text: str) -> str:
    """광고마다 띄어쓰기와 문장부호가 달라서("책상에 탁!", "책상에탁") 이를 빼고 비교한다."""
    return re.sub(r"[\s.,!?;:'\"()\[\]{}~…]+", "", normalize(text))


def _has(token: str, text: str, squashed: str) -> bool:
    if token.startswith("date:"):
        return token[5:] in date_keys(text)
    if token.startswith("numdate:"):
        return token[8:] in number_date_keys(text)
    return _squash(token) in squashed


def case_applies(rule_id: str | None, text: str) -> bool:
    """사례에 조건이 적혀 있고 광고가 그중 하나도 충족하지 않을 때만 False."""
    groups = load_triggers().get(rule_id or "")
    if not groups:
        return True
    squashed = _squash(text)
    return any(all(_has(token, text, squashed) for token in group) for group in groups)
