# 2026-10-26 검수 실패 CP(`FAILED`) BE 대응 요청

Agent가 HTTP 202를 보낸 뒤 검수가 시간 초과나 예외로 끝나면, 이제 체크포인트 API로 `FAILED`를 보낸다.
BE가 이 요청을 받아 작업을 실패로 끝내 주면 된다. BE README의 후속 작업 "Agent 실행 예외의 비동기 실패 전달"에 해당한다.

## 왜 필요한가

- 지금은 Agent가 실패하면 로그만 남기고 BE에 아무것도 보내지 않는다.
- BE 작업은 `RUNNING`으로 남아 24시간 뒤 `ReviewJobCleaner`가 지울 때까지 그대로이고, FE는 그동안 계속 결과를 조회한다.
- BE에는 실패 처리(`ReviewProgressService.fail` → `review_failed` SSE, `/result` 409 `REVIEW_FAILED`)가 이미 있고 FE도 처리한다.
  **비어 있는 것은 Agent가 실패를 알려 올 입구뿐이다.**

## 요청 형식

`PATCH /api/v1/reviews/checkpoint`, 헤더 `X-Internal-Key` (기존과 같음)

```json
{
  "original_text_id": "a0000000-0000-4000-8000-000000000001",
  "checkpoint_level": "FAILED",
  "error": {
    "code": "REVIEW_TIMEOUT",
    "message": "검수 제한 시간(60초)을 넘겼습니다.",
    "stage": "FINAL_ASSESSMENT",
    "trace_id": "trace_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
}
```

| 필드 | 값 |
|---|---|
| `checkpoint_level` | `FAILED` (새 값) |
| `error.code` | `REVIEW_TIMEOUT`(제한 시간 초과) \| `REVIEW_ERROR`(실행 중 예외) |
| `error.message` | 로그용 한국어 문장. 예외 종류 이름만 담고 광고 문구는 담지 않는다. 화면에 그대로 보여 주는 용도는 아니다 |
| `error.stage` | 실패할 때 진행 중이던 단계(`AgentStage`의 7단계 중 하나). 어떤 단계도 시작하기 전이면 `null` |
| `error.trace_id` | 접수 응답(202)의 trace_id. `COMPLETED`의 `result.trace_id`와 같은 용도 |

- `error`는 `FAILED`에만 넣고, `FAILED`에는 항상 넣는다. `FAILED`에 `result`는 넣지 않는다.
- 한 검수에서 `COMPLETED`와 `FAILED` 중 **하나만** 보낸다. 둘 다 보내는 경우는 없다.
- `FAILED`도 다른 CP처럼 순서대로 보낸다. 앞서 끝난 단계 CP가 먼저 도착한다.
- 5xx나 연결 오류면 한 번 재시도하고, 4xx면 재시도하지 않는다(기존 규칙과 같음).

## BE에서 할 일 (제안)

1. **요청 받기**: `CheckpointRequest.checkpointLevel`은 `AgentStage` 타입이라 지금은 `"FAILED"`를 읽지 못한다.
   - **주의**: `original_text.checkpoint_level`에 CHECK 제약이 있어서(V1 migration), `AgentStage`에 `FAILED`를 추가하고
     `OriginalText.moveTo(FAILED)`를 그대로 부르면 DB 오류가 난다.
   - 방법은 둘 중 하나다. ① `FAILED`를 받되 `moveTo`는 부르지 않는다(DB 단계는 마지막 성공 단계로 둔다).
     ② CHECK 제약에 `FAILED`를 추가하는 migration을 넣는다. 기존 BE 실패 경로(`ReviewWorkflow`)도 DB 단계를 바꾸지 않으니 ①이 더 일관된다.
2. **`error` 필드**: `CheckpointRequest`에 `@Valid` `error`를 추가하고, `FAILED`이면 필수, 그 밖의 단계이면 거부(400)한다.
3. **실패 처리**: `CheckpointService.save`에서 `FAILED`이면 다음 순서로 처리한다.
   - 이미 `COMPLETED`이거나 작업이 끝났으면 무시한다(기존 `COMPLETED` 처리와 같음).
   - `job.getAgentTraceId()`가 있는데 `error.trace_id`와 다르면 거부한다(기존 `result.trace_id` 검사와 같음).
   - 커밋 후 이벤트로 `ReviewProgressService.fail(...)`을 부른다. 작업이 메모리에 없으면 `getOrRegister`로 만든 뒤 실패 처리한다.
4. **오류 코드 연결**: `JobError`의 code와 message는 BE의 `ErrorCode`를 쓰고, Agent의 message는 로그에만 남기는 것을 권한다.
   - `REVIEW_TIMEOUT` → `AGENT_TIMEOUT` ("Agent 검수 대기 시간이 초과되었습니다.")
   - `REVIEW_ERROR` → `AGENT_UNAVAILABLE` ("Agent 검수 실행에 실패했습니다.")
5. **실패 단계 표시**: 지금 `ReviewJob.fail`은 `currentStage`를 실패로 표시한다. CP 흐름에서 `currentStage`는 **마지막으로 성공한 단계**라서,
   그 단계가 실패로 잘못 바뀐다. `error.stage`가 있으면 그 단계를 실패로 표시하는 것을 권한다.

`FAILED`는 화면에 보이는 "검수 단계"가 아니라 작업이 끝났다는 신호다. SSE `checkpoint` 이벤트로 `FAILED` 단계를 보내지 말고 `review_failed`만 보내면 FE를 고칠 필요가 없다.

## 확인할 테스트 (제안)

- `FAILED` + `error` → 작업 `FAILED`, `review_failed` SSE 발행, `/result` 409 `REVIEW_FAILED`
- `FAILED`인데 `error` 없음, 또는 다른 단계에 `error` 있음 → 400
- `COMPLETED` 이후 늦게 온 `FAILED`, `FAILED` 이후 늦게 온 `COMPLETED` → 무시, 상태 유지
- `error.trace_id`가 접수 trace_id와 다름 → 400
- `error.stage`가 `null` → 실패 처리는 하고, 단계 표시는 기존 기본값을 쓴다

## BE 반영 전에 Agent가 먼저 배포되면

BE는 `"FAILED"`를 `AgentStage`로 읽지 못해 `400 VALIDATION_ERROR`로 응답한다(`GlobalExceptionHandler.handleUnreadable`).
Agent는 4xx라서 재시도하지 않고 로그에 `checkpoint not saved ... level=FAILED http=400`을 남긴다.
작업은 지금처럼 `RUNNING`에 머물고, 잘못된 상태는 저장되지 않는다. 즉 BE를 반영할 때까지는 지금과 같다.

## 이번 범위가 아닌 것

- **결과 대기 만료**: Agent 프로세스가 죽거나 재시작되거나, BE가 계속 응답하지 않으면 `FAILED`도 도착하지 않는다.
  이 경우는 BE가 일정 시간 뒤 스스로 실패 처리해야 한다. Agent 제한 시간은 `REVIEW_TIMEOUT_SECONDS`(기본 60초)다.

## Agent 쪽 변경 위치 (참고)

- `ai-agent/app/services/review.py`: 시간 초과·예외 시 `checkpoint.fail(...)`
- `ai-agent/app/checkpoint.py`: `FAILED` CP를 기존 순서 큐로 전송
- `business-mcp/business_mcp/schemas.py`: `CheckpointLevel`에 `FAILED`, `CheckpointError` 추가
- `business-mcp/business_mcp/tools/save_checkpoint.py`: `error` 검증 후 BE로 그대로 전달
