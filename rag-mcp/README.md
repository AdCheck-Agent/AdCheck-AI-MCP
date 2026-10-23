# RAG-MCP: pgvector / CSV·XLSX 기업 문서

사회·역사 문서는 저장소에서 관리하고, 실제 기업 문서는 Backend가 CSV 또는 XLSX로 전달합니다.
광고 검수 입력은 기존 Agent의 JSON `text`입니다. PDF·이미지·DOCX 업로드는 지원하지 않습니다.
이 서비스에는 실제 pgvector 검색과 MCP Tool이 있으며 최종 LLM 판정은 Agent 담당 범위입니다.

MVP에서는 현재 사회·역사 문서 묶음을 고정 기준으로 사용합니다. 사회 문서 수정·폐기
워크플로우 개발은 이번 범위에 포함하지 않습니다. 기업 문서는 검수 시 첨부한 파일의 내용 전체를 반환합니다.
파트 2는 검색 결과의 반환·state 보존까지 담당하고, MCP 호출 흐름과 최종 판단은 파트 1 담당입니다.

## 1. 기업 문서 형식

파일 하나는 기업 하나의 문서 하나입니다. 첫 행은 아래 영문 헤더입니다.
CSV는 UTF-8 또는 UTF-8 BOM, XLSX는 `policies` 시트 하나를 사용합니다.
셀 병합·제목용 별도 행·숨은 보조 시트·수식 대신 평평한 표와 값을 사용하세요.

| 컬럼 | 필수 값 | 형식·의미 |
|---|---|---|
| `row_id` | O | 문서 내 고유 정책 항목 ID, 영문·숫자·`_ - . :`, 최대 100자 |
| `company_id` | O | BE에서 정한 기업 ID, 동일한 ID 문자 규칙, 최대 100자 |
| `document_id` | O | BE 문서 ID, 최대 150자. 파일 내 모든 행이 같아야 함 |
| `document_type` | O | 아래 세 가지 코드 중 하나 |
| `title` | O | 문서 제목, 최대 200자 |
| `section` | O | 해당 정책 항목/보고서 절 제목, 최대 200자 |
| `content` | O | 실제 정책·보고 내용, 1~20,000자. 한 행은 한 항목 |
| `source_url` | 빈 값 허용 | 실제 출처 http(s) URL. 없으면 빈 셀, 가짜 주소 입력 금지 |
| `published_at` | 빈 값 허용 | 실제 발행일 `YYYY-MM-DD` 또는 Excel 날짜. 업로드일과 다름 |

헤더는 9개 모두 필요합니다. 순서는 바꿔도 되지만 누락·중복·추가 컬럼은 거부합니다.
각 파일의 `company_id`, `document_id`, `document_type`, `title`은 동일해야 합니다.
문서는 최신본만 유지합니다. 같은 document_id로 다시 올리면 교체되며, **version은 RAG가 자동으로 매깁니다.**
처음 올리면 `v1`, 같은 파일을 다시 올리면 그대로, 내용이 바뀌면 `v2`, `v3`…으로 올라갑니다.
같은 광고를 다시 검수했을 때 각 결과가 어떤 판의 기준을 썼는지 이 값으로 구분합니다.
문서를 삭제한 뒤 다시 올리면 새 문서로 보고 `v1`부터 시작합니다.
내용을 임의로 다듬거나 빈 칸을 만들어 채우지 않습니다. 오류에는 행 번호와 컬럼 정보를 반환합니다.

| 문서 구분 | document_type | 샘플 파일명 |
|---|---|---|
| 기업가치 | `corporate_values` | `corporate_values.csv` / `.xlsx` |
| 지속가능경영보고서 | `sustainability_report` | `sustainability_report.csv` / `.xlsx` |
| 윤리경영 정책 | `ethics_policy` | `ethics_policy.csv` / `.xlsx` |

원래 보고서가 PDF라면 기업/BE 측에서 항목별 내용을 이 형식으로 정리해 전달합니다.
이 서버는 PDF 변환이나 OCR을 하지 않습니다. 수치·단위·기간·적용 범위는 content에 함께 적어야 합니다.
정책·목표·달성 실적을 구분하고 원문에 없는 인증·수치를 추가하지 마세요.

두 예시 기업의 각 3종 문서는 `data/corporate/{company_id}/`에 CSV와 XLSX로 있습니다.
두 확장자는 내용이 같으므로 **둘 중 하나만 업로드**하면 됩니다.

## 2. 행 단위 chunking과 검색

- 다른 행을 합치지 않고 한 정책 행의 content를 기본 chunk로 사용합니다.
- 긴 행은 모델 tokenizer 기준 최대 512토큰, 64토큰 겹침으로 **같은 크기로 고르게** 분할합니다. (`RAG_CHUNK_TOKENS`, `RAG_CHUNK_OVERLAP`)
  고정 간격으로 자르면 짧은 끝 조각(예: 출처 이름만 남은 줄)이 생겨 무관한 질문에도 상위에 올랐습니다.
- 모든 조각에 row_id·기업·문서·유형·section·버전·출처와 파일 내 순서를 보존합니다.
- 사회 문서는 heading별로 나누어 기관 사실·보도 사례·프로젝트 기준을 유지합니다.
  본문 markdown 링크는 표시 문구만 남기고 주소는 빼고 임베딩합니다. 주소는 근거의 `source_urls`에 있습니다.
- 다국어 모델 `BAAI/bge-m3`(1024차원)를 FastEmbed 사용자 정의 ONNX 모델로 등록해 사용합니다. 로드 확인: `python -m rag_mcp.cli check-embedding`
- 로컬 CPU 추론이며 API key는 필요 없습니다. 최초 처리 시 모델 파일(약 2.2GB)을 다운로드합니다.
- pgvector `vector(1024)`에 저장하고 `<=>` cosine distance로 정렬합니다. score는 `1 - distance`이며 사실 확률이 아닙니다.
- 초기 규모에서는 exact search를 사용합니다. 기업 필터를 먼저 적용하므로 다른 기업 결과로 top-k를 채우지 않습니다.
- 임베딩 모델이 DB profile과 다르면 검색·적재를 거부합니다. 모델 교체는 별도 DB/재적재로 진행합니다.

## 3. 실행

저장소 루트에서 실행합니다.

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp -n .env.example .env
docker compose up --build -d
```

포트: Agent 8000 / RAG 8001 / Business 8002 / pgvector 호스트 5433, 컨테이너 5432.
`docker compose`는 DB readiness 확인 후 RAG 전용 schema를 초기화하고 서버를 시작합니다.
초기화는 표를 삭제하지 않으며 BE의 회원·금기어 테이블을 만들거나 변경하지 않습니다.
사회 문서 적재는 별도 명령으로 실행합니다.

```bash
docker compose exec rag-mcp python -m rag_mcp.cli ingest-social
curl -fsS http://localhost:8001/ready
```

로컬 Python 서버로 개발하려면 RAG 컨테이너와 같은 포트를 동시에 사용하지 마세요.

```bash
docker compose stop rag-mcp
docker compose up -d pgvector
PYTHONPATH=rag-mcp python -m rag_mcp.cli init-db
PYTHONPATH=rag-mcp python -m rag_mcp.cli ingest-social
python -m uvicorn rag_mcp.server:app --app-dir rag-mcp --port 8001
```

`/health`는 모델 다운로드·DB 접속 없이 살아 있음을 확인하고, `/ready`는 DB/schema/profile을 확인합니다.
`/ready`가 성공해도 모델 가중치가 내려받아졌다는 의미는 아닙니다.
사회 문서는 manifest의 social 항목만 적재합니다. 기업 문서는 자동 적재하지 않습니다.

## 4. BE → RAG: 기업 문서 등록·교체

`PUT /api/v1/companies/{company_id}/documents/{document_id}`

`multipart/form-data`: `file` 하나, 선택 `expected_revision` 정수.
기본 한도는 5MiB·1,000행입니다. 한 검수에 파일 3개를 첨부한다면 BE가 문서별로 이 API를 호출합니다.
업로드·임베딩·DB commit이 완료된 뒤 동기 응답합니다. 작업 queue/background job은 없습니다.

```bash
curl -fsS -X PUT \
  http://localhost:8001/api/v1/companies/taegeon_beauty/documents/taegeon_beauty-corporate_values \
  -F 'file=@rag-mcp/data/corporate/taegeon_beauty/corporate_values.csv' \
  -F 'expected_revision=0'
```

예시 응답:

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

실제 chunk_count는 tokenizer와 내용에 따라 달라집니다.
기업 파일의 기업·문서 ID는 BE의 값으로 작성합니다.

- URL의 기업·문서 ID와 파일 값이 다르면 422입니다.
- 같은 파일을 재전송해도 중복 chunk를 만들지 않습니다. 기존 revision을 유지합니다.
- 내용·chunk 구성이 바뀌면 기존 chunk를 하나의 transaction에서 교체하고 revision과 version을 올립니다.
- expected_revision=0은 신규 문서 생성, 기존 문서는 조회한 revision을 지정하면 충돌 시 409입니다.
- expected_revision을 생략하면 마지막으로 commit된 요청이 해당 문서의 최신 내용입니다.
- 파싱·임베딩·DB 작업에 실패하면 이전 정상 문서와 chunk는 유지합니다.
- CSV/XLSX 원본 파일 보관은 BE 담당입니다. RAG는 추출 내용·metadata·벡터를 저장합니다.

## 5. BE → RAG: 상태 조회·삭제

```text
GET    /api/v1/companies/{company_id}/documents/{document_id}
DELETE /api/v1/companies/{company_id}/documents/{document_id}
```

GET 응답은 위 DocumentResult와 같습니다. DELETE는 문서·모든 chunk를 함께 삭제하고 204를 반환합니다.
해당 기업에 문서가 없으면 404입니다. 다른 기업의 동일한 문서 ID는 영향을 받지 않습니다.

BE는 인증된 사용자의 기업 ID를 결정한 뒤 호출해야 합니다.
현재 서비스는 내부 개발용으로 별도 인증을 구현하지 않았습니다. URL의 ID는 end-user 권한을 증명하지 않습니다.
사용자가 직접 선택한 임의 기업 ID를 검증 없이 전달하는 방식으로 공개하지 마세요.

## 6. Agent → RAG: 검색 REST / 실제 MCP

검색 REST는 진단·연동용으로 유지합니다.

```bash
curl -fsS http://localhost:8001/tools/search_social_context \
  -H 'Content-Type: application/json' \
  -d '{"query":"역사적 사건을 할인 행사에 사용하는 표현","top_k":5,"min_score":0.0}'

curl -fsS http://localhost:8001/tools/search_corporate_value \
  -H 'Content-Type: application/json' \
  -d '{"query":"외모로 구매를 압박하는 광고","company_id":"taegeon_beauty"}'
```

입력: query 필수, top_k 기본5·최대20, min_score 기본0·범위[-1,1]. 기업 검색은 company_id 필수입니다.

### 검수 시 첨부한 파일 전체 반환

BE는 파일별 업로드가 `indexed`로 완료된 뒤, 그 응답의 `document_id` 목록을 검수 요청과 함께
Agent에 전달해야 합니다. Agent는 기업 검색 REST/MCP 호출에 `document_ids`를 전달합니다.

```json
{
  "query": "모든 협력업체의 노동환경을 윤리적으로 관리합니다",
  "company_id": "seojun_roasters",
  "document_ids": ["seojun_roasters-corporate_values", "seojun_roasters-ethics_policy"]
}
```

- `document_ids`를 주면 **순위를 매기지 않고 해당 문서의 조각을 전부** 반환합니다.
  첨부한 순서대로, 각 문서 안에서는 파일의 행 순서대로 정렬하며 `top_k`·`min_score`는 적용하지 않습니다.
  광고와 어긋나는 항목이 유사도 순위에서 밀려 빠지는 일을 막기 위한 동작입니다. `score`는 참고값입니다.
- 첨부 문서 본문 합계가 `RAG_MAX_ATTACHED_CHARS`(기본 30,000자)를 넘으면 일부만 자르지 않고
  `status: too_large`와 빈 evidence를 반환합니다. MCP `isError`가 아닌 정상 응답입니다.
- `document_ids`: 1~100개, 각 ID는 업로드와 같은 문자 규칙·최대 150자입니다.
- 선택하지 않은 기존 문서는 반환되지 않습니다. 지정 문서가 없거나 다른 기업 소유이면
  해당 문서는 결과에서 제외하며, 다른 문서로 검색 범위를 넓히지 않습니다.
- 빈 목록은 REST 422 / MCP Tool 오류입니다. 첨부 파일이 없으면 기업 검색 호출을 생략합니다.
- 생략 또는 null은 기존처럼 기업 전체에서 유사도 순위 상위 `top_k`개를 검색합니다.
  **첨부 파일로 검수할 때는 반드시 document_ids를 전달해야 합니다.**
- 이 행 순서는 `ordinal` 도입 후 업로드한 문서부터 적용됩니다. 이전에 올린 문서는 다시 업로드하세요.
- 현재 문서 ID는 같은 기업 안에서 교체되는 저장 단위입니다. 같은 ID의 서로 다른 내용을
  동시에 업로드하는 검수를 구분하려면 검수별 ID·revision 고정 계약을 별도로 정해야 합니다.

응답은 `status: ok|empty|too_large`, `mock:false`, `evidence`, `message`, `related_criteria`입니다.
근거마다 document, section, snippet, rule_id, version, document_id, chunk_id, company_id,
document_type, record_type, source_urls, source_ids, row_id, score를 보존합니다.
업로드 정책의 rule_id는 해당 row_id입니다. 빈 검색 결과와 검색 실패를 구분합니다.

### 검색 결과 state 보존

| 검색 | 전체 결과를 보관하는 Agent state 필드 |
|---|---|
| 사회·역사 | `social_context_result` |
| 기업 가치 | `corporate_value_result` |
| 외부검색 | `external_search_result` |

사회·기업 노드는 기존 evidence 목록과 함께 결과 객체 전체를 저장합니다.
각 결과의 `related_criteria: list[str]`는 FE 초안의 ‘관련 검수 기준’ 태그를 담을 자리입니다.
현재 검색 서비스는 태그를 생성하지 않으며 기본값 `[]`를 반환합니다. 기존 호출 흐름·판정·분기는
변경하지 않았습니다. 검색되지 않은 사회·기업 결과는 None이며, 호출 실패는 해당 result의
`status: error`와 기존 `rag_errors`에 기록합니다. 성공했지만 근거가 없으면 `status: empty`입니다.

태그 생성 담당은 미확정입니다. 파트 1이 실제 광고 문맥과 검색 근거를 함께 읽고 태그를 작성한 뒤,
state 및 최종 FE 응답에 연결하는 방안을 제안합니다. 검색되었다는 사실만으로 적용 기준이나
위반 여부를 확정하지 않습니다. FE HTML의 키워드 판정 규칙은 구현에 가져오지 않았습니다.
최종 사용자 API의 Evidence 모델 확장·태그 노출은 별도 파트 1 작업입니다.

오늘 작업 및 전달 사항: [2026-10-22 작업 기록](../docs/2026-10-22-rag-mcp-handoff.md).

실제 MCP endpoint는 `http://localhost:8001/mcp`이며 SDK v1.30.0의 Streamable HTTP를 사용합니다.
Tool: `search_social_context`, `search_corporate_value`.
MCP 입력 인자는 위 검색 모델과 같고 반환은 structuredContent에 담습니다.
Agent의 `RagMCPTransportClient`가 초기화·Tool 호출·오류 확인을 담당합니다.
기존 `RagMCPClient`는 HTTP 대체 adapter로 유지했습니다.
Agent의 사회·기업 검색 노드에 실제 MCP client를 연결했습니다. 로컬 .env의 RAG_RETRIEVAL_ENABLED=true로 활성화하며 Compose에서는 기본으로 켭니다.
DB·MCP 호출 실패는 rag_errors로 기록하고 needs_review로 보류합니다. company_id가 없으면 기업 검색을 생략합니다. LLM 판정은 아직 mock입니다.

## 7. 오류 응답

```json
{"error":{"code":"IDENTITY_MISMATCH","message":"파일의 기업·문서 ID가 URL과 다릅니다.","retryable":false}}
```

| HTTP | 코드 | 의미 |
|---|---|---|
| 413 | FILE_TOO_LARGE | 업로드 용량 초과 |
| 415 | UNSUPPORTED_FILE_TYPE | PDF 등 미지원 확장자 |
| 422 | INVALID_DOCUMENT / IDENTITY_MISMATCH | 형식·행·기업/문서 ID 불일치 |
| 409 | REVISION_CONFLICT | 문서가 다른 요청에 의해 갱신됨 |
| 404 | DOCUMENT_NOT_FOUND | 해당 기업의 문서 없음 |
| 503 | STORAGE_UNAVAILABLE | DB·schema·모델 profile 문제 |
| 503 | EMBEDDING_UNAVAILABLE | 모델 다운로드·추론 실패 |

요청 자체의 타입 오류는 FastAPI 기본422입니다. MCP Tool 오류는 SDK의 isError로 전달됩니다.

## 8. 테스트

```bash
python -m pytest -q
python -m ruff check .
```

DB 통합 테스트에는 이름이 `_test`로 끝나는 별도 DB를 준비합니다.
아래 예시는 실제 서비스용 adcheck_rag와 다른 DB입니다.

```bash
docker compose exec pgvector createdb -U adcheck adcheck_rag_test
RAG_TEST_DATABASE_URL=postgresql://adcheck:adcheck@localhost:5433/adcheck_rag_test \
  python -m pytest rag-mcp/tests -q
```

통합 테스트는 test DB의 RAG 문서를 지우며 모델 다운로드 없이 테스트용 임베딩을 사용합니다.
일반 테스트는 파일 검증·CSV/XLSX 동등성·사회 manifest 선택을 확인합니다.
실제 모델·MCP 실행 확인은 별도 smoke 검증으로 구분합니다.

### 검색 품질 평가 (실제 임베딩)

`tests/fixtures/retrieval_cases.json` 문항으로 hit@k·MRR·기업 격리·무관 문구 점수·지연 시간을 측정합니다.
DB의 RAG 문서를 지우고 사회 문서와 기업 CSV 전체를 다시 적재하므로 `_eval`/`_test` DB만 허용합니다.

```bash
docker compose exec pgvector createdb -U adcheck adcheck_rag_eval
PYTHONPATH=rag-mcp python -m rag_mcp.evaluation \
  --database-url postgresql://adcheck:adcheck@localhost:5433/adcheck_rag_eval \
  --output docs/eval/retrieval-baseline.json
```

기준선 결과와 해석: [2026-10-22 검색 평가](../docs/2026-10-22-rag-retrieval-eval.md).
점수는 관련성 구분 기준으로 쓸 수 없으며, 결과 존재를 근거 충분으로 해석하지 않습니다.

## 9. Backend와 합의할 범위

- 문서 유형 코드 3개, 기업·문서 ID, 원본 파일 보관과 접근 권한
- 업로드 요청 timeout과 indexed/실패 상태 표시
- 문서 수정 때 같은 document_id로 교체할지 별도 이력을 남길지
- 검수에 첨부한 파일의 document_ids를 BE·Agent에 연결
- 현재 pgvector는 AI 개발용 독립 DB. BE PostgreSQL과 합칠 때 접속·권한·migration 소유권 결정

금기어 RDB·LLM 최종 판정·Frontend는 이 변경에서 구현하지 않습니다.
Business/Tavily 검색의 기존 작업은 유지합니다.

## 최종 확인 기록

- CSV 6개와 XLSX 6개의 내용 동등성·컬럼 검증 완료
- 별도 pgvector test DB를 포함한 전체 테스트 87개 통과, Ruff lint/format 통과
- 실제 로컬 임베딩으로 사회 문서 12개 적재·검색 확인
- CSV/XLSX 업로드·재전송·기업 격리·삭제 smoke 검증 완료
- 실제 MCP Tool 호출과 Agent 그래프 → MCP → pgvector 연결 확인
- LLM 판정은 mock. 검색 기준선 평가: 23문항 hit@5 0.96, 기업 격리 위반 0건 (개발용 문항 기준)
- 기업가치 방향성 행 추가 후 기업 hit@5 0.88. 이에 따라 document_ids 지정 시 첨부 문서 전체를 반환하도록 변경
