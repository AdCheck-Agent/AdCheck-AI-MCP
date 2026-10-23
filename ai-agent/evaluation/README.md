# 평가셋

`cases.json`은 광고 문구와 검색 근거 fixture, 기대 status를 담은 평가 케이스입니다.

- `tests/test_eval_cases.py`: 케이스마다 `scripted`(가짜 모델 응답)를 넣어 **코드 가드와 분기**가
  기대 status로 이어지는지 확인합니다. 실제 LLM 호출이 없어 CI에서 항상 실행됩니다.
- `run_eval.py`: `OPENAI_API_KEY`가 있을 때 **실제 모델**로 같은 케이스를 돌려 기대 status와
  비교합니다. 프롬프트·모델을 바꾼 뒤 정확도를 볼 때 직접 실행합니다.

```bash
PYTHONPATH=ai-agent python ai-agent/evaluation/run_eval.py
```

`scripted`의 `"__error__"`는 모델 호출 예외를 흉내 냅니다. 케이스를 추가할 때는
`evidence`(source: social | corporate)와 `expected_status`를 채웁니다.

`real_model: true`인 케이스만 실제 모델 평가에 쓰입니다. 입력만으로 기대 status가 정해지는
케이스(근거 없음, 명확히 평범한 문구 등)만 표시하고, 모델 고장·지어낸 근거처럼 가짜 모델로만
재현되는 케이스는 표시하지 않습니다. 실제 모델 평가에 케이스를 더하려면 `real_model`을 true로 둡니다.

## 품질 점검표 (AI 출력 품질 점검) 만들기

`real_model: true` 케이스 23건이 점검표의 입력입니다. 케이스마다 `type`(답 가능 · 답 불가 ·
실패 유도)과 `expected_note`(기대 결과와 근거)가 있고, 평가셋 버전은 `harness.EVAL_SET_VERSION`입니다.
케이스를 더하거나 기대값을 바꾸면 버전을 올려, 개선 전 · 후가 같은 평가셋으로 비교되게 합니다.

```bash
# 개선 후 (현재 코드)
PYTHONPATH=ai-agent python ai-agent/evaluation/run_eval.py --label after --csv after.csv

# 개선 전: 이전 커밋의 코드에 현재 평가셋을 덮어 실행
git worktree add ../adcheck-before <개선 전 커밋>
cp -r ai-agent/evaluation ../adcheck-before/ai-agent/
(cd ../adcheck-before && PYTHONPATH=ai-agent python ai-agent/evaluation/run_eval.py \
  --label before --csv ../before.csv)
```

CSV는 표 열(No · 유형 · 점검 입력 · 기대 결과 · 실제 출력 요약 · 충족 · 비고)과 같고, 첫 줄에
모델 · 프롬프트 버전(git 해시) · 평가셋 · 실행일이 들어갑니다.
