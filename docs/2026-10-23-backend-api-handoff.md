# 2026-10-23 BE ↔ AI 서비스 API 정리 (파트 2)

BE와 AI 서비스가 주고받는 API와 합의할 사항을 정리했다.
상세 계약은 [RAG 가이드](../rag-mcp/README.md)와 [guide.md](../guide.md)를 참고한다.

## 한눈에 보기

```text
BE ──① PUT/GET/DELETE 기업 문서──▶ rag-mcp :8001   (검수 전에 문서 등록)
BE ──② POST 검수 요청────────────▶ ai-agent :8000  (202 접수, document_ids로 첨부 문서 지정)
                                     └─▶ rag-mcp / business-mcp  (Agent가 내부 호출, BE는 호출하지 않음)
BE ◀─③ PATCH 체크포인트──────────── business-mcp save_checkpoint  (단계 완료, 마지막에 최종 결과)
```

| 순서 | API | 호출 주체 → 대상 | 용도 |
|---|---|---|---|
| ① | `PUT /api/v1/companies/{company_id}/documents/{document_id}` | BE → RAG | 기업 문서 등록·교체 |
| ① | `GET /api/v1/companies/{company_id}/documents/{document_id}` | BE → RAG | 등록 상태 조회 |
| ① | `DELETE /api/v1/companies/{company_id}/documents/{document_id}` | BE → RAG | 문서 삭제 |
| ② | `POST /api/v1/reviews` | BE → Agent | HTTP 202 접수 응답 후 백그라운드 검수 |
| ③ | `PATCH /api/v1/reviews/checkpoint` | Business-MCP → BE | 단계 완료 보고, `COMPLETED`에 최종 결과 (`X-Internal-Key`) |
| - | `GET /health`, `GET /ready`(RAG만) | BE → 각 서비스 | 상태 확인 |

BE는 RAG의 검색 API(`/tools/*`, `/mcp`)와 Business-MCP를 직접 호출하지 않는다. Agent가 내부에서 호출한다.

## ① BE → RAG: 기업 문서 등록·교체

### 등록·교체

`PUT /api/v1/companies/{company_id}/documents/{document_id}`, `multipart/form-data`

| 필드 | 필수 | 설명 |
|---|---|---|
| `file` | 예 | CSV(UTF-8) 또는 XLSX(`policies` 시트 하나). 5MiB·1,000행 이하 |
| `expected_revision` | 아니오 | 동시 수정 방지용 정수. 새 문서는 `0`, 교체는 조회한 `revision` |

```bash
curl -X PUT http://localhost:8001/api/v1/companies/taegeon_beauty/documents/taegeon_beauty-corporate_values \
  -F 'file=@corporate_values.csv' -F 'expected_revision=0'
```

```json
{
  "company_id": "taegeon_beauty",
  "document_id": "taegeon_beauty-corporate_values",
  "document_type": "corporate_values",
  "title": "태건뷰티 기업가치",
  "version": "v1",
  "revision": 1,
  "chunk_count": 8,
  "status": "indexed"
}
```

- 임베딩·DB 저장까지 끝난 뒤 동기 응답한다. 응답을 받으면 바로 검수에 쓸 수 있다.
- 같은 `document_id`로 다시 올리면 교체된다.
  - 내용이 같으면 `version`·`revision`이 그대로이다.
  - 내용이 바뀌면 v1 → v2로 올라간다.
  - `version`은 RAG가 매기므로 파일에 적지 않는다.
- 파일 3개를 첨부한 검수라면 문서마다 한 번씩, 총 3번 호출한다.

### 파일 형식 (7개 컬럼)

`row_id, document_type, title, section, content, source_url, published_at`

- 기업·문서 ID는 파일에 적지 않는다. RAG는 URL의 `{company_id}`, `{document_id}`를 그대로 쓴다.
  따라서 BE가 업로드 순간에 만든 UUID를 사용자 파일을 고치지 않고 그대로 쓸 수 있다.
- `company_id`·`document_id` 열이 남아 있는 예전 형식 파일도 받는다. 그 값은 쓰지 않고 URL의 ID를 쓴다.
- URL의 ID에는 영문·숫자와 `_ - . :`만 쓸 수 있다(UUID 가능). 기업 100자, 문서 150자 이하.
  규칙에 맞지 않으면 `422 INVALID_IDENTITY`.
- `document_type`: `corporate_values` | `sustainability_report` | `ethics_policy`
- `source_url`·`published_at`은 비워도 된다.
- 예시 파일: [rag-mcp/data/corporate/](../rag-mcp/data/corporate/)
- 컬럼 설명: [RAG 가이드 1장](../rag-mcp/README.md)

### 조회·삭제

- `GET`: 위 등록 응답과 같은 형식을 반환한다. 없으면 `404 DOCUMENT_NOT_FOUND`.
- `DELETE`: 성공하면 `204`, 없으면 `404 DOCUMENT_NOT_FOUND`.

### 오류 응답

```json
{ "error": { "code": "INVALID_DOCUMENT", "message": "컬럼을 확인하세요. 필수 헤더: ...", "retryable": false } }
```

| HTTP | code | 의미 |
|---|---|---|
| 413 | `FILE_TOO_LARGE` | 5MiB 초과 |
| 415 | `UNSUPPORTED_FILE_TYPE` | CSV·XLSX 외 형식(PDF 등) |
| 422 | `INVALID_DOCUMENT` | 헤더·컬럼·값 오류, 중복 `row_id`, 행 수 초과, 수식 포함 등. `message`에 행 번호가 있다 |
| 422 | `INVALID_IDENTITY` | URL의 기업·문서 ID가 문자 규칙·길이에 맞지 않음 |
| 404 | `DOCUMENT_NOT_FOUND` | 조회·삭제 대상 없음 |
| 409 | `REVISION_CONFLICT` | `expected_revision`이 현재 값과 다름. 다시 조회한 뒤 재시도 |
| 503 | `STORAGE_UNAVAILABLE`, `EMBEDDING_UNAVAILABLE` | DB 또는 임베딩 모델 일시 장애. `retryable: true` |

## ② BE → Agent: 검수 요청

`POST /api/v1/reviews`, `application/json`

```json
{
  "text": "광고 문구",
  "context": {
    "channel": "sns",
    "campaign_name": "가을 캠페인",
    "company_id": "6f1c2a4e-0b7d-4c1e-9a55-3d2f8e9b1c00",
    "document_ids": ["1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed"]
  },
  "review_id": "a0000000-0000-4000-8000-000000000001"
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `text` | 예 | 검수할 문구. 2,000자 이하 |
| `context.channel` | 예 | 현재 `"sns"`만 허용 |
| `context.campaign_name` | 아니오 | 100자 이하. 판정에는 쓰지 않는다 |
| `context.campaign_purpose` | 아니오 | 200자 이하. 판정 프롬프트에 들어간다 (현재 BE는 보내지 않음) |
| `context.scheduled_at` | 아니오 | 게시 예정 시각(시간대 포함 ISO). 문구 속 날짜를 이 기준으로 판단한다 (현재 BE는 보내지 않음) |
| `context.company_id` | 아니오 | 없으면 기업 가치 검토를 하지 않고 `missing_information`에 남긴다 |
| `context.document_ids` | 아니오 | 이번 검수에 첨부한 문서 ID 목록. 1~100개 |
| `review_id` | 아니오 | BE의 `original_text_id`(UUID). 있어야 체크포인트를 보낸다 |

- `document_ids`를 주면 RAG가 해당 문서의 내용 **전체**를 첨부 순서대로 Agent에 넘긴다.
- `document_ids`가 없으면 그 기업의 등록 문서 전체에서 문구와 비슷한 상위 5개만 쓴다.
- 등록되지 않았거나 다른 기업의 `document_id`는 오류 없이 결과에서 빠진다.
  따라서 BE는 ①의 등록 응답을 받은 문서 ID만 보낸다.
- 첨부 문서 본문 합계가 30,000자를 넘으면 기업 근거 없이 처리하고, 사유를 표시하며 `pass`로 끝나지 않게 막는다.
- 알 수 없는 필드를 보내면 `422`가 난다.

접수 응답 예시 (HTTP 202):

```json
{
  "status": "accepted",
  "trace_id": "trace_0123456789abcdef0123456789abcdef"
}
```

- Agent는 접수 응답을 먼저 전송하고 FastAPI BackgroundTasks에서 검수를 실행한다.
- 작업 ID, 상태 조회 API, SQLite 큐는 사용하지 않는다. 입력 JSON 형식은 유지한다.
- 검수 결과 모델은 기존 형식을 유지한다. `CHECKPOINT_ENABLED=true`이고 `review_id`가 있으면
  Agent → Business MCP `save_checkpoint` → BE CP 저장 API로 완료한 단계를 전송한다.
  마지막 `COMPLETED`에는 검증된 최종 응답을 `result`로 함께 보낸다. BE가 저장 후 완료 SSE를 발행한다.
- 실행 함수는 `app/services/review.py`의 `run_review`다. BackgroundTasks의 반환값은 자동 전송되지 않는다.
- 실행 제한은 `REVIEW_TIMEOUT_SECONDS`(기본 60초)이며, 완료 상태·실행 오류·시간 초과는 trace_id로 로그에 남긴다.
- 입력 오류는 기존 HTTP 422다. 202 응답 후 실행 오류를 같은 요청의 HTTP 500/504로 반환하지 않는다.
- 서버 프로세스 내부에서 실행하므로 서버 재시작 후 작업 복구는 제공하지 않는다.

최종 CP 형식 (`X-Internal-Key`는 Business 설정에서 읽으며 Tool 인자로 받지 않는다):

```json
{
  "original_text_id": "a0000000-0000-4000-8000-000000000001",
  "checkpoint_level": "COMPLETED",
  "result": {
    "status": "needs_review",
    "summary": "게시 맥락 확인 필요",
    "findings": [],
    "related_criteria": [],
    "missing_information": [],
    "trace_id": "trace_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
}
```

`needs_review`도 정상 완료이다. 실행 예외·시간 초과로 검수를 끝내지 못하면 `COMPLETED` 대신 `FAILED`를 보낸다.

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

- `error.code`: `REVIEW_TIMEOUT`(시간 초과) | `REVIEW_ERROR`(실행 예외)
- `error.stage`: 실패할 때 진행 중이던 단계. 어떤 단계도 시작하기 전이면 `null`
- `error.trace_id`: 접수 응답의 trace_id. `COMPLETED`의 `result.trace_id`와 같은 용도
- `error`는 `FAILED`에만, `FAILED`에는 반드시 넣는다. `result`는 넣지 않는다.
- BE 대응 요청은 [실패 CP 전달 문서](2026-10-26-failed-checkpoint-handoff.md)에 정리했다.

CP는 순서대로 전송하고 재시도 가능 오류는 한 번 재시도한다.
CP 전송이 끝내 실패하면 로그로 남긴다. BE·Agent 연결 장애로 마지막 CP 자체가 도착하지 않는 경우에 대비한 BE 대기 만료는 후속 작업이다.

검수 결과 구조 예시 (접수 응답과 별개):

```json
{
  "status": "needs_review",
  "summary": "...",
  "findings": [
    {
      "detection_type": "SEMANTIC",
      "category": "corporate_value",
      "severity": "medium",
      "quote": "문제 구절",
      "reason": "판정 이유",
      "evidence": [
        { "document": "태건뷰티 기업가치", "section": "약속", "snippet": "근거 원문", "rule_id": "taegeon_beauty-corporate_values-008", "version": "v1", "source": "corporate" }
      ],
      "suggestion": "수정 제안",
      "needs_human_review": true
    }
  ],
  "related_criteria": ["취약성·직업·장애 등을 이용한 조롱 방지"],
  "missing_information": [],
  "trace_id": "trace_0123456789abcdef0123456789abcdef"
}
```

- `status`: `pass` | `revise` | `needs_review`
- `detection_type`: `BANNED_WORD`(금기어 일치) | `SEMANTIC`(모델이 의미로 판단)
- `related_criteria`: 화면의 "관련 검수 기준" 태그. 지적이 없으면 빈 목록
- `missing_information`: 확인하지 못한 항목(기업 ID 없음, 검색 실패, 첨부 문서 과대, 외부검색 실패)
- `needs_review`에는 수정안(`suggestion`)이 없다
- `evidence.version`: 판정에 쓴 문서 판(v1, v2…). 같은 광고를 다시 검수했을 때 기준 문서가 바뀌었는지 구분하는 데 쓴다.
- 응답 형식은 파트 1(Agent) 담당이며 바뀔 수 있다. 최신 형식은 `ai-agent/app/schemas/review.py`를 기준으로 한다.

## 합의가 필요한 사항

1. ~~검수 요청에 `context.document_ids` 전달~~ → BE 구현 완료(업로드가 끝난 문서 ID만 전달)
2. ~~ID 규칙~~ → BE가 발급해 URL로만 전달, 파일에는 적지 않음
3. ~~호출 순서~~ → BE는 모든 첨부가 `indexed`인 뒤 검수 요청
3-1. **`campaign_purpose`·`scheduled_at` 전달 여부**: Agent는 판정에 쓰지만 BE·FE에는 입력이 없다.
4. **기업 문서 없이 검수하는 경우**: 기업 가치 검토를 생략할지, 사람 검토로 보낼지 정해야 한다. BE·FE·파트 1이 함께 정한다.
5. **접근 제한**: RAG 문서 API에는 인증이 없다. 외부에 공개하지 말고 BE만 접근할 수 있는 내부망에 두어야 한다.
6. **삭제 동기화**: BE에서 문서를 지우면 RAG `DELETE`도 호출해야 한다.
7. **업로드 timeout과 상태 표시**: 업로드는 임베딩까지 끝나야 응답하므로 몇 초 걸릴 수 있다.
   BE의 timeout 값과 화면에 보여 줄 처리 중·완료(`indexed`)·실패 상태를 정한다.
8. **원본 파일 보관**: RAG는 원본 파일을 보관하지 않는다. 원본 보관과 접근 권한은 BE가 맡는다.
9. **DB 통합**: 기본은 Compose pgvector다. Supabase로 옮기려면 `RAG_COMPOSE_DATABASE_URL`만 설정하면 되며
   ([RAG 가이드](../rag-mcp/README.md) 3장), RAG 표는 `adcheck_rag` schema에만 만든다. 옮길지와 관리 주체를 정한다.
10. **체크포인트 키**: AI와 BE의 `INTERNAL_API_KEY`가 같아야 한다. Compose에서 맥의 BE는 `http://host.docker.internal:8080`.

## 주소와 상태 확인

| 서비스 | 로컬 주소 | Compose 내부 주소 | 상태 확인 |
|---|---|---|---|
| Agent | `http://localhost:8000` | `http://ai-agent:8000` | `GET /health` |
| RAG | `http://localhost:8001` | `http://rag-mcp:8001` | `GET /health`, `GET /ready`(DB 포함) |

- `/health`: 서버가 살아 있는지만 확인한다.
- `/ready`: DB와 schema까지 확인한다. 업로드 전 확인에 쓴다.
