# 2026-10-22 Business MCP 작업 및 파트 1 전달 사항

작업 브랜치: `feat/business-mcp-transport`

## 이번에 완료한 내용

- HTTP API만 있던 Business 서버에 실제 MCP `/mcp`와 `search_recent_issue` Tool을 추가했다.
- 기존 HTTP endpoint는 유지해 현재 Agent의 호출을 계속 지원한다.
- MCP 입력·출력 schema를 공개하고, 검색 결과 전체를 `structuredContent`로 반환한다.
- 정상 결과·빈 결과·실패를 구분한다. 실패 상태도 메시지와 함께 반환한다.
- 잘못된 검색어는 검색 전에 거부하고, 기존 Tavily 5초·최대 3개·재시도 없음 제한을 유지한다.
- Agent, 금칙어, RAG 데이터·검색 코드는 이번 작업에서 수정하지 않았다.

## 파트 1에서 연결할 내용

1. **MCP client 연결:** 기존 Business HTTP adapter를 MCP SDK 호출로 교체한다.
   로컬은 `http://localhost:8002/mcp`, Compose 내부는 `http://business-mcp:8002/mcp`다.
   `initialize` 후 `search_recent_issue`에 `{"query": "확인할 공개 사실"}`을 전달한다.
   SDK 세션 생성·정리와 전체 대기 시간 제한도 client에서 관리한다.
2. **state 보존:** `structuredContent`를 수신 모델로 검증하고 전체를 `external_search_result`에 저장한다.
   검색 근거 목록은 기존 `external_evidence`에도 보존한다.
   기존 state 필드는 이미 있으며, 이번에 새 state를 만든 것은 아니다.
3. **실패 구분:** `isError: true`여도 구조화된 결과가 있으면 `timeout`, `unavailable`, `error`와
   메시지를 보존한다. 입력 오류·연결 실패처럼 구조화된 결과가 없는 경우에는 client 실패로 처리한다.
   정상 검색의 `empty`와 호출 실패를 같은 빈 결과로 합치지 않는다.
4. **Agent 정책:** 검색어 생성, 검색 필요 여부, 검수당 1회 제한, 충분성 판단과 최종 판정을 연결한다.
   서버의 각 Tool 호출은 독립적이며 서버가 검수별 호출 횟수를 추적하지 않는다.
5. **관련 검수 기준:** `related_criteria` 필드는 반환·보존되지만 기본값은 `[]`이며 생성 기능은 없다.
   실제 사용한 근거를 바탕으로 파트 1의 판정 단계에서 생성하는 방안은 아직 팀 합의가 필요하다.
   최종 FE 응답 노출도 BE·FE와 별도로 합의한다.

| 검색 상태 | MCP isError | 의미 |
|---|---|---|
| ok | false | 결과 있음 |
| empty | false | 검색 성공, 결과 없음 |
| unavailable | true | API key 미설정 |
| timeout | true | Tavily 검색 제한 시간 초과 |
| error | true | 공급자·네트워크·응답 형식 오류 |

## 검증 결과와 한계

- 전체 pytest: **98개 통과, DB 연결이 필요한 7개 건너뜀**.
- 전체 Ruff lint, Business 영역 format 검사 통과.
- MCP SDK 초기화·Tool 목록·호출, 입력 검증, 상태·메타데이터 보존, 호스트 검증을 테스트했다.
- 기존 Agent HTTP adapter 관련 테스트도 통과했다.
- 중립적인 NASA 검색어로 실제 Tavily를 1회 호출해 `ok`, 결과 1개, 출처 메타데이터를 확인했다.
  키·검색 결과 본문은 출력하지 않았다.
- MCP 구간은 ASGI transport로 확인했다. 실제 배포 포트·프록시와 FE→BE→Agent 전체 연결은 별도 검증이다.
- 검색 품질, 기사 사실 검증, 관련 검수 기준 생성은 이번 테스트의 검증 대상이 아니다.

이전 첨부 문서 필터·state 작업과 남은 연결 사항은
[RAG·MCP 전달 문서](2026-10-22-rag-mcp-handoff.md)에 정리되어 있다.
