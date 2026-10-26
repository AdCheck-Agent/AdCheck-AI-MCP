import json
import unicodedata
from pathlib import Path

from app.graph.state import ReviewState, RuleHit

RULES_PATH = Path(__file__).resolve().parents[2] / "rules" / "banned_expressions.json"


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def load_rules(rules_path: Path = RULES_PATH) -> list[RuleHit]:
    # TODO: DB 소유권이 정해지면 JSON 대신 RDB/API에서 불러온다.
    return [RuleHit.model_validate(item) for item in json.loads(rules_path.read_text("utf-8"))]


def match_rules(text: str, rules: list[RuleHit]) -> list[RuleHit]:
    normalized = normalize(text)
    return [rule for rule in rules if rule.enabled and normalize(rule.expression) in normalized]


def find_rule_hits(text: str, rules_path: Path = RULES_PATH) -> list[RuleHit]:
    return match_rules(text, load_rules(rules_path))


def rule_filter(state: ReviewState) -> dict:
    return {"rule_hits": find_rule_hits(state["source_text"])}
