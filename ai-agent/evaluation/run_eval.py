"""Run the evaluation cases against the real model (needs OPENAI_API_KEY)."""

import sys
from collections import Counter

from app.core.config import get_settings
from app.llm.openai_model import create_openai_model

from evaluation.harness import load_cases, run_case


def main() -> int:
    model = create_openai_model(get_settings())
    if model is None:
        print("OPENAI_API_KEY가 없어 실제 모델 평가를 건너뜁니다.")
        return 1
    cases = [c for c in load_cases() if c.get("real_model")]
    matched, confusion = 0, Counter()
    for case in cases:
        got = run_case(case, model).status
        ok = got == case["expected_status"]
        matched += ok
        confusion[(case["expected_status"], got)] += 1
        mark = "OK  " if ok else "FAIL"
        print(f"{mark} {case['id']:<12} expected={case['expected_status']:<12} got={got}")
    print(f"\n일치 {matched}/{len(cases)}")
    for (want, got), n in sorted(confusion.items()):
        print(f"  기대 {want} -> 결과 {got}: {n}건")
    unsafe = confusion[("needs_review", "pass")] + confusion[("revise", "pass")]
    print(f"위험한 오판(사람 검토/수정 대상을 pass로 통과): {unsafe}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
