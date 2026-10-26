"""Combination conditions for reported cases.

A reported case (Starbucks 탱크데이, 무신사 양말 광고, ...) became a controversy because of a
*combination* of date and wording, not because one of its words appeared. A retrieval hit or a
model judgment that rests on a single shared word ("탱크톱", "5월 18일 새 텀블러") is not a match.
`app/rules/case_triggers.json` lists, per case rule_id, the combinations that do count; a case
that is not listed there is never filtered.
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
    """Spacing and punctuation vary in ads ("책상에 탁!", "책상에탁"); compare without them."""
    return re.sub(r"[\s.,!?;:'\"()\[\]{}~…]+", "", normalize(text))


def _has(token: str, text: str, squashed: str) -> bool:
    if token.startswith("date:"):
        return token[5:] in date_keys(text)
    if token.startswith("numdate:"):
        return token[8:] in number_date_keys(text)
    return _squash(token) in squashed


def case_applies(rule_id: str | None, text: str) -> bool:
    """False only when the case has listed conditions and the ad meets none of them."""
    groups = load_triggers().get(rule_id or "")
    if not groups:
        return True
    squashed = _squash(text)
    return any(all(_has(token, text, squashed) for token in group) for group in groups)
