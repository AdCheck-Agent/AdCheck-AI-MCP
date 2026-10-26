# 검수 적발 유형과 위치 계약

- 금기어 적발의 원본은 BE `banned_word` 사전이다. BE가 광고 원문 전체에서 포함 검색한다. Agent의 내부 표현 목록은 의미 검토의 참고 신호이며 모든 Agent 적발은 `SEMANTIC`이다.
- Agent `Finding`은 실제 원문 `quote`, `start_offset`, `end_offset`, `needs_human_review`를 전달한다. 위치는 Java/JavaScript와 동일한 UTF-16 코드 단위의 `[start, end)`이다.
- 같은 표현이 반복되면 발생 위치별 지적을 반환한다. 같은 위치에 서로 다른 검토 의견은 유지한다.
- BE는 위치를 검증한 후 유지한다. 구버전의 위치 없는 응답은 모든 일치 위치로 확장하며, 지적·대안 ID를 함께 연결한다.
- 대안 적용은 위치로 수행한다. 같은 구간의 같은 대안은 한 번만 적용하고, 서로 다른 대안이나 겹치는 구간은 충돌로 처리한다. 직접 편집된 구간을 추측해 덮어쓰지 않는다.
- BE가 추가한 사전 적발은 AI 판정이 통과여도 유지한다. 대안이 없는 사전 적발은 직접 수정이 필요하다. 판정의 원본과 BE의 통합 판정은 구분한다.
- 화면은 BE의 `decision`, `summary_text`를 사용하고 `agent_result`는 원본 AI 판정으로 보존한다.

연결 이슈: AdCheck-Agent/AdCheck-BE#17, AdCheck-Agent/AdCheck-AI-MCP#29, AdCheck-Agent/AdCheck-FE#7.
배포 순서: BE(새 위치 필드 수용 및 구버전 지원) → AI → FE. 기존 202 접수와 COMPLETED CP 결과 전달은 유지한다.
