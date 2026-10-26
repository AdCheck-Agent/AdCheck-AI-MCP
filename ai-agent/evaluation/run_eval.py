"""실제 모델로 평가 케이스를 실행한다(OPENAI_API_KEY 필요).

    PYTHONPATH=ai-agent python ai-agent/evaluation/run_eval.py [--label before] [--csv out.csv]

--csv는 "AI 출력 품질 점검" 시트에 쓰는 표를 저장한다(UTF-8 BOM, 엑셀에서 열림).
"""

import argparse
import csv
import datetime
import subprocess
import sys
from collections import Counter

from app.core.config import get_settings
from app.llm.openai_model import create_openai_model

from evaluation.harness import EVAL_SET_VERSION, load_cases, missing_quotes, run_case


class RecordingModel:
    """실제 모델을 감싸고 원본 응답을 보관해, 실패한 케이스를 설명할 수 있게 한다."""

    def __init__(self, inner) -> None:
        self.inner, self.raw = inner, []

    def generate(self, system: str, user: str) -> str:
        try:
            answer = self.inner.generate(system, user)
        except Exception as exc:
            # 그래프는 호출 실패를 needs_review로 바꾸므로, 숨기지 말고 이유를 보여 준다.
            body = getattr(getattr(exc, "response", None), "text", "")
            print(f"     모델 호출 오류: {type(exc).__name__}: {exc} {body[:300]}")
            raise
        self.raw.append(answer)
        return answer


def prompt_version() -> str:
    """이번 실행을 만든 코드의 짧은 git 해시 (여기서 말하는 '프롬프트 버전')."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def output_summary(response) -> str:
    quotes = ", ".join(f.quote for f in response.findings) or "없음"
    return f"{response.status} · 지적: {quotes} · {response.summary}"


def write_csv(
    path: str, rows: list[list], header: dict[str, str], matched: int, total: int
) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "모델",
                header["model"],
                "프롬프트 버전",
                header["prompt"],
                "평가셋",
                header["set"],
                "실행일",
                header["date"],
            ]
        )
        writer.writerow([])
        writer.writerow(
            ["No", "유형", "점검 입력", "기대 결과 (근거 포함)", "실제 출력 요약", "충족", "비고"]
        )
        writer.writerows(rows)
        writer.writerow([])
        writer.writerow(["결과", f"{matched}/{total}", f"충족률 {matched / total * 100:.0f}%"])


def run_once(cases: list[dict], model: RecordingModel, wins: Counter) -> tuple[int, Counter, list]:
    """케이스를 한 바퀴 실행한다. `wins`는 케이스 id별로 몇 번 맞았는지 센다."""
    matched, confusion, rows = 0, Counter(), []
    for number, case in enumerate(cases, start=1):
        model.raw.clear()
        response = run_case(case, model)
        got = response.status
        missed = missing_quotes(case, response)
        ok = got in [case["expected_status"], *case.get("also_ok", [])] and not missed
        matched += ok
        wins[case["id"]] += ok
        confusion[(case["expected_status"], got)] += 1
        mark = "OK  " if ok else "FAIL"
        print(f"{mark} {case['id']:<22} expected={case['expected_status']:<12} got={got}")
        note = f"빠뜨린 표현: {missed}" if missed else ""
        if not ok:
            if missed:
                print(f"     빠뜨린 표현: {missed}")
            print(f"     요약: {response.summary}")
            for finding in response.findings:
                print(f"     지적: {finding.quote!r} / {finding.reason}")
            for raw in model.raw:
                print(f"     모델 원본: {' '.join(raw.split())}")
        rows.append(
            [
                number,
                case.get("type", ""),
                case["text"],
                case.get("expected_note", ""),
                output_summary(response),
                "충족" if ok else "미충족",
                note or case["id"],
            ]
        )
    return matched, confusion, rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="", help="이 실행의 이름 (예: before, after)")
    parser.add_argument("--csv", default="", help="결과를 저장할 CSV 경로")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="N번 반복해 평균과 흔들리는 문항을 보여 줍니다 (결과가 달라질 수 있어서)",
    )
    args = parser.parse_args()

    settings = get_settings()
    real = create_openai_model(settings)
    model = RecordingModel(real) if real is not None else None
    if model is None:
        print("OPENAI_API_KEY가 없어 실제 모델 평가를 건너뜁니다.")
        return 1
    cases = [c for c in load_cases() if c.get("real_model")]
    repeat = max(1, args.repeat)
    runs, wins, unsafe_runs = [], Counter(), []
    for run_number in range(1, repeat + 1):
        if repeat > 1:
            print(f"\n===== {run_number}/{repeat}회차 =====")
        matched, confusion, rows = run_once(cases, model, wins)
        runs.append(matched)
        unsafe_runs.append(confusion[("needs_review", "pass")] + confusion[("revise", "pass")])
        if run_number == 1:
            first_rows, first_matched = rows, matched
        print(f"\n일치 {matched}/{len(cases)} ({matched / len(cases) * 100:.0f}%)")
        for (want, got), n in sorted(confusion.items()):
            print(f"  기대 {want} -> 결과 {got}: {n}건")
        print(f"위험한 오판(사람 검토/수정 대상을 pass로 통과): {unsafe_runs[-1]}건")
    if repeat > 1:
        print(f"\n===== {repeat}회 요약 (평가셋 {EVAL_SET_VERSION}, {len(cases)}건) =====")
        print(f"회차별 일치: {runs}  평균 {sum(runs) / repeat:.1f}/{len(cases)}")
        print(f"회차별 위험한 오판: {unsafe_runs}")
        shaky = [(c["id"], wins[c["id"]]) for c in cases if 0 < wins[c["id"]] < repeat]
        broken = [c["id"] for c in cases if wins[c["id"]] == 0]
        print("매번 틀림:", ", ".join(broken) or "없음")
        print("흔들림(일부만 맞음):", ", ".join(f"{i} {w}/{repeat}" for i, w in shaky) or "없음")
    rows, matched = first_rows, first_matched
    if args.csv:
        header = {
            "model": settings.openai_model,
            "prompt": f"{prompt_version()} {args.label}".strip(),
            "set": EVAL_SET_VERSION,
            "date": datetime.date.today().isoformat(),
        }
        write_csv(args.csv, rows, header, matched, len(cases))
        print(f"CSV 저장: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
