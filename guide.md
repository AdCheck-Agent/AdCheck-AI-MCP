# AdCheck AI 개발·실행 가이드

이 문서는 현재 구현 상태, 파트별 남은 작업, 실행 방법과 연동 기준을 정리합니다.
파트 1은 **AI Agent·판정**, 파트 2는 **데이터·검색·MCP** 담당입니다.
RAG 업로드·검색 계약은 [RAG 가이드](rag-mcp/README.md), BE 연동은 [BE ↔ AI API 정리](docs/2026-10-23-backend-api-handoff.md)를 기준으로 합니다.

## 1. 현재 어디까지 되어 있나

**검수 파이프라인 전 단계가 실제로 동작합니다.** `OPENAI_API_KEY`가 없으면 판정을 mock(`needs_review`)으로 대신합니다.

| 영역 | 현재 구현 | 남은 작업 |
|---|---|---|
| AI Agent | 검수 접수 HTTP 202, BackgroundTasks 실행, 실행 제한·오류 로그 | 서버 재시작 시 작업 복구 없음 |
| LangGraph | 노드 분리, 조건 분기, 외부검색 후 재판정, 단계 이벤트 | |
| 금기어 | JSON 규칙 정규화·매칭, 모델이 빠뜨린 금기어 지적 보정(`BANNED_WORD`) | RDB 또는 규칙 조회 API 연결 |
| 사회·역사 검색 | 기준 6개·사례 6개, bge-m3 임베딩, pgvector 검색, 평가 | 평가 문항 확충 |
| 기업 가치 검색 | CSV/XLSX 업로드(ID는 URL에서), 기업 격리, 첨부 문서 전체 반환, version 자동 부여 | |
| LLM 판정 | OpenAI(`gpt-4o-mini`, JSON·temperature 0), 근거 카탈로그 인용, 관련 검수 기준 태그 | 기업 근거보다 무관한 사회 근거를 고르는 경우 보완 |
| 대안 문구 | 지적별 수정안, 원문·금기어·근거 단어 재사용 검사, 재시도 1회 | 숫자 말장난 등 글자만 바뀐 수정안, 수정안 적용본 재검사 |
| 출력 검증 | 원문에 없는 인용·검색에 없는 근거 제거, 상태 불일치 시 `needs_review`, `missing_information` | |
| MCP | RAG·Business 실제 MCP 서버, Agent의 MCP client 2개 | |
| 외부검색 | 판정 노드가 검색어 생성(개인정보 제거), 검수당 1회 Tavily | |
| BE 보고 | 단계별 체크포인트, 마지막 `COMPLETED`에 최종 결과 포함 | |
| Docker | 4개 서비스, pgvector·모델 볼륨, 외부 DB 선택(`RAG_COMPOSE_DATABASE_URL`) | 시작 직후 bge-m3 첫 로드 지연 |

최근 검증 결과 (2026-10-23):

- pytest 297개 통과 (전용 pgvector test DB 포함. DB 없이 실행하면 289개 통과·8개 건너뜀), Ruff lint 통과
- 검색 품질 평가 (bge-m3, 512토큰 조각): 전체 hit@1 0.81·MRR 0.87, 사회 hit@1 1.00, 기업 hit@1 0.63, 격리 위반 0건
  ([검색 평가](docs/2026-10-22-rag-retrieval-eval.md))
- Docker Compose: 4개 서비스 healthy, BE와 같은 UUID로 CSV 업로드 → 첨부 문서 검색, 예전 9개 컬럼 파일도 업로드 성공
- 실제 모델: 탱크데이 문구 `revise`(근거 `CASE-HIST-001`, 수정안·태그 포함), 평범한 문구 `pass`
- 알려진 문제: 컨테이너 시작 직후 첫 검수는 bge-m3 로드로 RAG 검색이 10초 timeout을 넘겨 `needs_review`가 될 수 있음

## 2. 전체 구조와 파일 찾기

```text
FE ─JWT─▶ BE(Spring, Supabase)
            ├─ PUT 기업 문서 ─────────────▶ rag-mcp :8001 → pgvector
            └─ POST /api/v1/reviews ─────▶ ai-agent :8000  (202 accepted)
                                             └─ LangGraph
                                                  ├─ 금기어 탐지 (JSON, 향후 RDB)
                                                  ├─ 사회·역사 / 기업 가치 검색 → rag-mcp (MCP)
                                                  ├─ LLM 판정 ─ 필요 시 외부검색 → business-mcp (MCP) → Tavily
                                                  ├─ 수정안 생성
                                                  └─ 출력 검증
            ◀─ PATCH /api/v1/reviews/checkpoint ── business-mcp save_checkpoint ◀─ 단계 완료·최종 결과
```

Compose의 Agent는 실제 RAG MCP를 호출합니다. 로컬은 `RAG_RETRIEVAL_ENABLED`로 선택합니다.
BE·FE와 금기어 RDB는 Compose에 포함하지 않습니다.

| 경로 | 역할 |
|---|---|
| [ai-agent/app/main.py](ai-agent/app/main.py) | 시작 시 모델·MCP client·그래프 생성 |
| [ai-agent/app/api/routes/review.py](ai-agent/app/api/routes/review.py) | 입력 검증 후 202 접수, 백그라운드 작업 등록 |
| [ai-agent/app/services/review.py](ai-agent/app/services/review.py) | 검수 실행, 실행 제한, 단계 추적과 체크포인트 |
| [ai-agent/app/checkpoint.py](ai-agent/app/checkpoint.py), [events.py](ai-agent/app/events.py) | 단계 이벤트를 순서대로 BE에 보고 |
| [ai-agent/app/schemas/review.py](ai-agent/app/schemas/review.py) | BE와 공유하는 입력·결과 모델 |
| [ai-agent/app/graph/](ai-agent/app/graph/) | 상태, 노드 연결과 분기, 각 노드 |
| [ai-agent/app/llm/](ai-agent/app/llm/) | 판정 프롬프트·가드, 수정안, 관련 기준 목록, OpenAI 연결 |
| [ai-agent/app/clients/](ai-agent/app/clients/) | RAG·Business MCP client |
| [ai-agent/app/rules/banned_expressions.json](ai-agent/app/rules/banned_expressions.json) | RDB 연동 전 임시 금기어 |
| [ai-agent/evaluation/](ai-agent/evaluation/) | 판정 평가셋 v3(39건, 실제 모델용 23건), 기능 테스트 |
| [rag-mcp/rag_mcp/](rag-mcp/rag_mcp/) | 검색 서버, 업로드, 임베딩, 평가 |
| [rag-mcp/data/](rag-mcp/data/) | 사회 기준·사례 12개, 예시 기업 2곳 × 3종 |
| [business-mcp/business_mcp/](business-mcp/business_mcp/) | 외부검색·체크포인트 MCP 서버 |
| [docker-compose.yml](docker-compose.yml) | 컨테이너 구성과 포트·내부 URL |

## 3. 파트 1: AI Agent·판정 담당

목표는 **문구와 검색 근거로 검수 결과·이유·수정안을 반환하는 것**입니다. 판정·수정안·검증은 구현을 마쳤습니다.

판정 원칙 (코드 가드로도 적용):

- 금기어 hit만으로 `revise`를 확정하지 않고 광고 문맥을 함께 판단합니다. hit가 있으면 자동 `pass`하지 않습니다.
- 근거 부족, 불확실한 판단, 검색 서비스 실패는 `needs_review`로 보냅니다.
- 근거가 충분하고 위험이 확인되면 `revise`, 명확한 위험이 없으면 `pass`입니다. `pass`는 게시 승인이 아닙니다.
- 근거 문서에 없는 내용을 `evidence`로 만들지 않습니다. 모델은 근거 카탈로그의 ID만 인용합니다.
- 관련 검수 기준 태그는 [criteria.py](ai-agent/app/llm/criteria.py)의 10개 중에서만 고릅니다.

연동 테스트에서 확인된 남은 과제:

| 증상 | 원인 | 위치 |
|---|---|---|
| "518원 할인 혜택" → "518원 특별 할인 혜택" | 수정안 검사가 글자 일치만 봄. 근거의 "5·18"과 문구의 "518원"이 다른 단어로 취급됨 | `llm/alternative.py`, `validate_result.py` |
| 수정안 적용 후에도 같은 뜻이 남음 | 수정안을 적용한 최종 문구를 다시 판정하지 않음 | `generate_alternative.py` |
| 문구 일부만 지적, 같은 지적 중복 | 지적 누락·중복을 확인하는 단계 없음 | `llm/judge.py` |
| 기업 가치 위반에 무관한 사회 사례를 근거로 인용 | 사회 검색은 관련이 낮아도 상위 5개를 반환하고, 판정이 그중 하나를 고름 | `llm/judge.py` 프롬프트 |
| `needs_review`에 수정안 없음 | 설계상 `needs_review` 경로는 수정안을 만들지 않음. 참고 수정안 제공 여부는 결정 필요 | `graph/graph.py` |

결과가 `needs_review`일 때는 `summary`로 경로를 구분합니다. "수정안을 만들지 못해…"는 수정안 실패,
"검증 단계에서…"는 출력 검증 하향, 그 밖의 판정 문구는 판정 단계 보류입니다.

평가는 [평가셋 안내](ai-agent/evaluation/README.md)를 따릅니다. 자동 테스트는 가짜 모델 응답으로 분기를 검증하고,
`run_eval.py`·`functional_check.py`가 실제 모델로 정확도를 봅니다.

## 4. 파트 2: 데이터·검색·MCP 담당

목표는 **검수에 쓸 수 있는 근거를 출처와 함께 반환하는 것**입니다. 검색·업로드·MCP·외부검색은 구현을 마쳤습니다.

| 항목 | 현재 |
|---|---|
| 임베딩 | `BAAI/bge-m3` 1024차원, FastEmbed custom ONNX, 512토큰·64토큰 겹침 |
| 저장 | pgvector `adcheck_rag` schema, 기업별 scope 격리, 같은 내용은 version 유지 |
| 기업 업로드 | 7개 컬럼 CSV/XLSX, 기업·문서 ID는 URL에서 받음(예전 ID 컬럼은 무시) |
| 검색 Tool | `search_social_context`, `search_corporate_value`(`document_ids` 지정 시 첨부 문서 전체, 30,000자 초과 시 `too_large`) |
| Business Tool | `search_recent_issue`(Tavily), `save_checkpoint`(BE 보고) |
| 평가 | 31문항, `python -m rag_mcp.evaluation` (전용 `_eval` DB) |

남은 일:

- 컨테이너 시작 직후 bge-m3 첫 로드가 10초를 넘어 첫 검수가 보류되는 문제. RAG 시작 시 모델을 미리 불러오고
  `/ready`를 모델 로드 후 성공하도록 바꾸는 방안을 제안합니다.
- 평가 문항 확충, Supabase 실제 연결 확인([RAG 가이드](rag-mcp/README.md) 3장)

## 5. 금기어 RDB는 누가 어떻게 연결하나

**금기어 저장소는 향후 RDB입니다. 현재 JSON은 초기 실행용 샘플입니다.**
RDB에 저장한다는 이유만으로 탐지 노드 전체를 MCP로 옮길 필요는 없습니다.

```text
load_rules      규칙 데이터 로딩 (현재 JSON)
match_rules     정규화 + 활성 규칙 매칭
find_rule_hits  로딩과 매칭 조합
rule_filter     rule_hits를 LangGraph에 전달
```

DB 소유권과 조회 방식은 아직 확정되지 않았습니다.

| 담당 | 할 일 |
|---|---|
| Backend / DB 담당 | RDB를 Backend가 관리한다면 테이블·규칙 CRUD·조회 API 제공 |
| 파트 2 | 선택된 RDB/API/MCP 조회 adapter 구현, 규칙 형식 변환 |
| 파트 1 | adapter를 rule_filter에 연결, 탐지 결과를 판정에 반영 |

선택지: `Agent → Backend 규칙 조회 API → RDB`, `Agent → RDB 조회 adapter → RDB`,
`Agent → 금기어 MCP Tool → RDB`. 규칙 조회 실패를 "금기어 없음"으로 처리하지 않도록 오류·보류 정책도 함께 정합니다.

## 6. 두 파트의 연동 계약

```text
search_social_context(query)
search_corporate_value(query, company_id, document_ids=None)  # document_ids 지정 시 첨부 문서 전체 반환
search_recent_issue(query)                                    # Business MCP
save_checkpoint(original_text_id, checkpoint_level, result=None)  # Business MCP, result는 COMPLETED에만
```

검색 결과는 `social_context_result`·`corporate_value_result`에 통째로 보존하고 근거는 `*_evidence`에 넣습니다.
`company_id`가 없으면 기업 검색을 생략하고 `missing_information`에 남깁니다.

| 근거 필드 | 의미 |
|---|---|
| `document`, `section`, `snippet` | 문서명, 항목, 실제 검색된 내용 |
| `rule_id` | 기준 ID (기업 문서는 `row_id`) |
| `version` | 문서 판. 적재 시 RAG가 자동 부여, 재검수 시 기준이 바뀌었는지 구분 |

RAG 응답에는 이 밖에 `document_id`, `chunk_id`, `company_id`, `score`, `source_urls` 등이 있습니다.
`score`는 cosine 유사도일 뿐 관련성 판정 기준이 아니므로 판정에 쓰지 않습니다.

## 7. 로컬에서 구동하기: venv + pip

macOS / zsh 기준입니다. Python 3.12를 먼저 설치합니다.

```bash
cd AdCheck-AI-MCP
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp -n .env.example .env
```

새 터미널에서는 저장소로 이동해 `source .venv/bin/activate`만 실행하면 됩니다.

```bash
PYTHONPATH=ai-agent python -m app.main                                                    # Agent
python -m uvicorn rag_mcp.server:app --app-dir rag-mcp --host 0.0.0.0 --port 8001          # RAG
python -m uvicorn business_mcp.server:app --app-dir business-mcp --host 0.0.0.0 --port 8002 # Business
```

- RAG는 pgvector와 사회 문서 적재가 먼저 필요합니다([RAG 가이드](rag-mcp/README.md) 3장).
- Agent가 실제 RAG를 호출하게 하려면 `.env`의 `RAG_RETRIEVAL_ENABLED=true`로 바꾸고 재시작합니다.
- Docker로 같은 포트를 쓰는 중이면 먼저 `docker compose down`으로 중지합니다.

## 8. Docker Compose로 전체 구동

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose exec rag-mcp python -m rag_mcp.cli ingest-social   # 빈 DB일 때 한 번
```

| 서비스 | 호스트 포트 | 확인 |
|---|---:|---|
| Agent | 8000 | <http://localhost:8000/health> |
| RAG | 8001 | <http://localhost:8001/ready> (DB·schema 포함) |
| Business | 8002 | <http://localhost:8002/health> |
| pgvector | 5433 | `docker compose exec pgvector pg_isready -U adcheck -d adcheck_rag` |

```bash
docker compose logs -f ai-agent rag-mcp business-mcp
docker compose down        # 볼륨 유지. down -v는 DB·모델 캐시까지 삭제
```

- 처음 실행하면 bge-m3(약 2.3GB)를 `rag-models` 볼륨에 내려받습니다. 시작 직후에는 검색을 한 번 호출해 모델을 미리 올립니다.
- 임베딩 모델을 바꾸면 기존 DB를 쓸 수 없습니다(차원·profile 불일치). `rag-postgres` 볼륨을 지우고 다시 적재합니다.
- 코드 변경 후에는 `up --build -d`로 다시 빌드합니다.

## 9. 환경변수 사용 방법

설정 예시는 [.env.example](.env.example), 실제 값은 `.env`에 둡니다. `.env`는 Git과 build context에서 제외됩니다.

| 변수 | 용도 |
|---|---|
| `AI_AGENT_PORT`, `RAG_MCP_PORT`, `BUSINESS_MCP_PORT`, `RAG_DB_PORT` | 로컬 Agent 포트, Compose 호스트 포트 |
| `RAG_DB_USER`, `RAG_DB_PASSWORD`, `RAG_DB_NAME` | Compose pgvector 계정·DB |
| `RAG_MCP_URL`, `BUSINESS_MCP_URL`, `RAG_RETRIEVAL_ENABLED` | Agent가 호출할 주소, 실제 RAG 호출 여부(로컬 `false`, Compose `true`) |
| `RAG_DATABASE_URL` | 로컬 RAG의 DB 주소 |
| `RAG_COMPOSE_DATABASE_URL` | Compose rag-mcp의 외부 DB(Supabase 등). 비우면 pgvector 컨테이너 |
| `RAG_EMBEDDING_MODEL`, `RAG_EMBEDDING_DIM`, `RAG_MODEL_CACHE` | 임베딩 모델(`BAAI/bge-m3`, 1024), 모델 캐시 위치 |
| `RAG_MAX_UPLOAD_BYTES`, `RAG_MAX_ROWS`, `RAG_MAX_ATTACHED_CHARS` | 업로드 크기·행 수, 첨부 문서 본문 합계 상한 |
| `HTTP_TIMEOUT_SECONDS` | Agent의 RAG MCP 호출 timeout (기본 10초) |
| `REVIEW_TIMEOUT_SECONDS` | 백그라운드 검수 제한 (기본 60초) |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | 판정·수정안 모델. key가 없으면 mock |
| `TAVILY_API_KEY`, `TAVILY_TIMEOUT_SECONDS`, `TAVILY_MAX_RESULTS` | 외부검색 key, 최대 5초·3건 |
| `CHECKPOINT_ENABLED` | Agent의 BE 체크포인트 보고 여부 (기본 `false`) |
| `ADCHECK_BE_BASE_URL`, `INTERNAL_API_KEY` | Business가 체크포인트를 보낼 BE 주소와 `X-Internal-Key`. BE와 같은 값 |
| `LOG_LEVEL` | 로깅 수준 |

- 기존 `.env`가 있으면 `.env.example`이 바뀌어도 자동으로 반영되지 않습니다. 특히 임베딩 모델 값이 예전 MiniLM이면 RAG가
  "임베딩 모델 로드 또는 추론에 실패했습니다"로 실패하니 `RAG_EMBEDDING_MODEL=BAAI/bge-m3`, `RAG_EMBEDDING_DIM=1024`로 바꿉니다.
- Compose 안에서 맥의 BE를 부를 때는 `ADCHECK_BE_BASE_URL=http://host.docker.internal:8080`을 씁니다.
- `RAG_MAX_*`는 Compose `environment`에 전달하지 않으므로 컨테이너에서는 기본값을 씁니다.
- 새 변수는 `.env.example`, Settings, Compose `environment`를 함께 갱신합니다.

## 10. API 호출과 Backend 연동

BE가 호출하는 API는 **`PUT /api/v1/companies/{company_id}/documents/{document_id}`**(RAG)와
**`POST /api/v1/reviews`**(Agent)이고, BE가 받는 API는 **`PATCH /api/v1/reviews/checkpoint`**입니다.
요청·응답·오류 형식은 [BE ↔ AI API 정리](docs/2026-10-23-backend-api-handoff.md)에 있습니다.

```bash
curl -i http://localhost:8000/api/v1/reviews \
  -H 'Content-Type: application/json' \
  -d '{"text":"5·18 탱크데이! 책상에 탁 치면 억 소리 나는 할인","context":{"channel":"sns"}}'
# HTTP/1.1 202 {"status":"accepted","trace_id":"trace_..."}
```

- 입력: `text` 1~2,000자, `context.channel`은 `sns`. 선택 `campaign_name`·`campaign_purpose`·`scheduled_at`·`company_id`·
  `document_ids`, 최상위 `review_id`(BE의 `original_text_id`). 입력 오류는 FastAPI 기본 422입니다.
- 202 이후 결과는 HTTP로 돌려주지 않습니다. `CHECKPOINT_ENABLED=true`이고 `review_id`가 있으면 단계마다 체크포인트를 보내고,
  마지막 `COMPLETED`에 `ReviewResponse`를 담습니다. 실패한 단계와 건너뛴 단계는 보내지 않습니다.
- 실행 완료·오류·시간 초과는 `trace_id`와 함께 로그에 남습니다. 서버 재시작 후 작업 복구는 없습니다.
- `campaign_purpose`·`scheduled_at`은 판정에 쓰이지만 현재 BE는 보내지 않습니다. 광고 제목(BE의 `name`)은 Agent에 전달되지 않습니다.

RAG 검색을 직접 확인하려면:

```bash
curl -fsS http://localhost:8001/tools/search_social_context \
  -H 'Content-Type: application/json' -d '{"query":"사회적 맥락"}'
curl -fsS http://localhost:8001/tools/search_corporate_value \
  -H 'Content-Type: application/json' \
  -d '{"query":"윤리적 생산","company_id":"taegeon_beauty","document_ids":["taegeon_beauty-ethics_policy"]}'
```

## 11. 테스트와 자주 막히는 부분

```bash
python -m pip check
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m pytest ai-agent/tests -q    # 파트별 실행
```

| 증상 | 확인할 점 |
|---|---|
| Python 버전이 3.11 등으로 나옴 | `python3.12 -m venv .venv`로 만들었는지와 venv 활성화 |
| `No module named app` | 저장소 루트에서 `PYTHONPATH=ai-agent python -m app.main` 실행 |
| 포트 사용 중, Docker daemon 연결 실패 | Docker와 로컬 프로세스 포트 중복, Docker Desktop 실행 상태 |
| 변경 코드가 Docker에 반영되지 않음 | `docker compose up --build -d` |
| RAG "임베딩 모델 로드 또는 추론에 실패" | `.env`의 임베딩 모델이 예전 MiniLM인지 (9장) |
| RAG "DB 임베딩 모델이 다릅니다" | 모델을 바꾼 뒤 예전 DB를 쓰는 중. 볼륨을 지우고 다시 적재 |
| 시작 직후 첫 검수만 근거 없이 `needs_review` | bge-m3 첫 로드 지연. 검색을 한 번 호출해 모델을 올린 뒤 재시도 |
| 결과가 항상 `[MOCK]` `needs_review` | `OPENAI_API_KEY` 미설정 |
| BE 화면이 진행 중에서 멈춤 | `CHECKPOINT_ENABLED`, `ADCHECK_BE_BASE_URL`, 두 서비스의 `INTERNAL_API_KEY` 일치, business-mcp의 `checkpoint rejected` 로그 |
| 첨부 업로드가 "형식과 내용을 확인" 오류 | rag-mcp 로그의 422 메시지. 7개 컬럼·`document_type`·중복 `row_id` 확인 |
| 근거가 비어 있음 | 사회 문서 적재 여부, 기업 ID·업로드 문서·`document_ids` |

## 12. 다음 작업

1. 파트 1: 수정안 의미 검사(숫자 말장난·적용본 재판정), 지적 누락·중복, 기업 근거 우선 대조
2. 파트 2: bge-m3 시작 시 미리 로드, 평가 문항 확충, Supabase 연결 확인
3. 공통·BE: 금기어 RDB 소유·조회 계약, `campaign_purpose`·`scheduled_at` 전달 여부, FE의 CSV 형식 안내
4. 정상·수정·보류·오류 사례로 BE·FE까지 end-to-end 재확인
