import pytest
from evaluation.harness import load_cases, run_case

CASES = load_cases()


class ScriptedModel:
    def __init__(self, script: list[str]) -> None:
        self.script = list(script)

    def generate(self, system: str, user: str) -> str:
        item = self.script.pop(0)
        if item == "__error__":
            raise TimeoutError("model timeout")
        return item


def test_eval_set_is_large_and_covers_every_status() -> None:
    assert len(CASES) >= 20
    assert {c["expected_status"] for c in CASES} == {"pass", "revise", "needs_review"}
    assert len({c["id"] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_reaches_expected_status(case: dict) -> None:
    response = run_case(case, ScriptedModel(case["scripted"]))
    assert response.status == case["expected_status"], response.summary
    if response.status == "revise":
        assert all(f.suggestion and f.evidence for f in response.findings)
    if response.status == "pass":
        assert response.findings == []
