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
