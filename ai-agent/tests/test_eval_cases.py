import pytest
from evaluation.harness import load_cases, missing_quotes, run_case

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
    assert missing_quotes(case, response) == []
    if response.status == "revise":
        assert all(f.suggestion and f.evidence for f in response.findings)
    if response.status == "pass":
        assert response.findings == []


def test_real_model_set_is_ready_for_the_quality_sheet() -> None:
    """The quality sheet needs 20 inputs, incl. unanswerable and failure-inducing ones."""
    real = [c for c in CASES if c.get("real_model")]
    assert len(real) >= 23
    assert {c["type"] for c in real} == {"답 가능", "답 불가", "실패 유도"}
    assert all(c["expected_note"] for c in real)


def test_csv_matches_the_sheet_columns(tmp_path) -> None:
    import csv

    from evaluation.run_eval import write_csv

    out = tmp_path / "r.csv"
    header = {"model": "m", "prompt": "abc before", "set": "v2", "date": "2026-10-23"}
    write_csv(str(out), [[1, "답 가능", "문구", "기대", "실제", "충족", "pass-01"]], header, 1, 1)
    rows = list(csv.reader(out.open(encoding="utf-8-sig")))
    assert rows[2] == [
        "No",
        "유형",
        "점검 입력",
        "기대 결과 (근거 포함)",
        "실제 출력 요약",
        "충족",
        "비고",
    ]
    assert rows[-1] == ["결과", "1/1", "충족률 100%"]
