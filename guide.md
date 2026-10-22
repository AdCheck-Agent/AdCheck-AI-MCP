# AdCheck AI 개발·실행 가이드

RAG 최신 구현·CSV/XLSX 업로드 계약은 [RAG 가이드](rag-mcp/README.md)를 기준으로 확인하세요.
사회 문서는 저장소, 기업 문서는 업로드로 처리하며 PDF는 지원하지 않습니다.

이 문서는 현재 구현 상태, 파트별 후속 작업, 실행 방법과 연동 기준을 정리합니다.
파트 1은 **AI Agent·판정**, 파트 2는 **데이터·검색·MCP** 담당을 뜻합니다.
아래 담당 구분은 기존 README의 AI 1 / AI 2와 같습니다.

## 1. 현재 어디까지 되어 있나

**RAG 검색·MCP·외부검색은 실제로 동작하고, LLM 판정과 수정안 생성은 아직 mock입니다.** API key 없이 실행됩니다.

| 영역 | 현재 구현 | 남은 작업 |
|---|---|---|
| AI Agent | FastAPI, health, review API, 입력 검증 | 실제 모델 호출과 실패 처리 |
| LangGraph | 노드 분리, compile, 조건 분기, 외부검색 후 재판정, END 도달 | 각 노드의 실제 기능 연결 |
| 금기어 | JSON 로딩, 정규화, 활성 규칙 매칭 | RDB 또는 규칙 조회 API 연결 |
| 사회·역사 검색 | 저장소 문서 분할·임베딩·pgvector 검색, Agent 연결, 실제 임베딩 평가 | 검색 품질 개선 |
| 기업 가치 검색 | CSV/XLSX 업로드·교체·삭제, 기업 격리, 첨부 문서 전체 반환 | BE의 `document_ids` 전달 연결 |
| LLM 판정 | 근거 부족·불확실을 반환하는 mock | 문맥 판단, 근거 충분성 판정, findings 생성 |
| 대안 문구 | 수정 분기와 TODO | 실제 수정 문구 생성 |
| 출력 검증 | Pydantic schema 검증 | 근거 출처, 인용 범위, 판정 일관성 검증 |
| MCP | RAG·Business 실제 MCP 서버, Agent의 RAG MCP client | Business의 Agent MCP client 전환 |
| 외부검색 | Tavily 검색, MCP·HTTP 제공, 상태·출처 반환 | 파트 1의 검색어 생성·호출 정책 연결 |
| 실행 환경 | Python 3.12, venv, pip, requirements | 기능 추가에 따른 의존성·설정 갱신 |
| Docker | 서비스별 Dockerfile, Compose, pgvector 볼륨 | 실제 연동 후 환경변수·의존성 조정 |

현재 검수 API는 문구에 상관없이 다음 형태로 응답합니다. `trace_id`는 요청마다 달라집니다.

```json
{
  "status": "needs_review",
  "summary": "[MOCK] LLM 판정은 아직 구현하지 않았습니다. 검색 여부와 별개로 사람 검토가 필요합니다.",
  "findings": [],
  "trace_id": "trace_0123456789abcdef0123456789abcdef"
}
```

금기어 탐지는 실제로 동작하지만 결과는 그래프의 `rule_hits`에만 들어갑니다.
아직 LLM이 이를 해석하지 않으므로 API의 `findings`에는 표시하지 않습니다.
`pass`와 `revise` 분기도 존재하며 테스트용 판정 노드로 검증했습니다.
운영 mock 노드는 근거를 만들지 않으므로 현재 API에서는 `needs_review`만 나옵니다.

최근 검증 결과 (2026-10-23):

- pytest 118개 통과 (전용 pgvector test DB 포함. DB 없이 실행하면 110개 통과·8개 건너뜀), Ruff lint 통과
- 실제 임베딩으로 사회 문서 적재, 기업 문서 업로드, 첨부 문서 전체 반환, version 자동 부여 확인
- 검색 품질 평가: hit@5 0.90, 기업 격리 위반 0건 ([검색 평가](docs/2026-10-22-rag-retrieval-eval.md))
- Docker Compose `up --build`: 4개 서비스 healthy, Agent·RAG·Business health와 RAG `/ready`, pgvector `pg_isready` 확인
- Compose 안에서 사회 문서 12개 적재, 기업 문서 6개 업로드(CSV·XLSX), 같은 파일 재업로드 시 version 유지 확인
- Agent에 `document_ids`를 포함한 검수 요청 → RAG MCP Tool 2회 호출(사회·기업) → pgvector 검색, 실패 기록 없이 HTTP 200
LLM 판정이 mock이므로 검수 결과의 정확도는 아직 검증 대상이 아닙니다.

## 2. 전체 구조와 파일 찾기

목표 연동 구조:

```text
Spring Boot Backend (별도 저장소)
  └─ REST → ai-agent :8000
               └─ LangGraph
                    ├─ 금기어 탐지 ← 향후 RDB / 규칙 조회 API
                    ├─ 사회·역사 검색 ─┐
                    ├─ 기업 가치 검색 ─┴→ rag-mcp :8001 → pgvector :5432
                    ├─ 필요 시 외부검색 → business-mcp :8002 → Tavily
                    ├─ LLM 판정
                    ├─ 수정안 생성
                    └─ 출력 검증
```

**Compose의 Agent는 실제 RAG MCP를 호출합니다.** 로컬은 RAG_RETRIEVAL_ENABLED 설정으로 선택합니다. Business 호출은 외부검색 분기 조건에 따릅니다.
Spring Boot, Frontend, 금기어 RDB는 현재 Compose에 포함하지 않습니다.

| 경로 | 역할 |
|---|---|
| [ai-agent/app/main.py](ai-agent/app/main.py) | Agent 실행, 시작 시 그래프 생성 |
| [ai-agent/app/api/routes/review.py](ai-agent/app/api/routes/review.py) | POST 검수 요청과 graph async invoke |
| [ai-agent/app/schemas/review.py](ai-agent/app/schemas/review.py) | Backend와 공유할 입력·응답 모델 |
| [ai-agent/app/graph/state.py](ai-agent/app/graph/state.py) | 요청별 그래프 상태와 trace ID 생성 |
| [ai-agent/app/graph/graph.py](ai-agent/app/graph/graph.py) | 노드 연결과 결과 분기 |
| [ai-agent/app/graph/nodes/](ai-agent/app/graph/nodes/) | 규칙·검색·판정·생성·검증 노드 |
| [ai-agent/app/clients/](ai-agent/app/clients/) | RAG MCP / Business HTTP adapter와 Protocol |
| [ai-agent/app/core/config.py](ai-agent/app/core/config.py) | Agent의 .env 설정 |
| [ai-agent/app/rules/banned_expressions.json](ai-agent/app/rules/banned_expressions.json) | RDB 연동 전 임시 규칙 |
| [rag-mcp/rag_mcp/](rag-mcp/rag_mcp/) | 검색 서버, Tool, Retriever / Embeddings 인터페이스 |
| [rag-mcp/data/](rag-mcp/data/) | 사회 기준·확인 사례 12개, 두 기업 문서 6개, 출처·적재 manifest |
| [business-mcp/business_mcp/](business-mcp/business_mcp/) | Tavily 외부검색 MCP·HTTP 서버 |
| [docker-compose.yml](docker-compose.yml) | 컨테이너 구성과 포트·내부 URL |
| [requirements.txt](requirements.txt) | 실행 의존성 |
| [requirements-dev.txt](requirements-dev.txt) | 실행 의존성 + pytest·Ruff |
| [pyproject.toml](pyproject.toml) | pytest와 Ruff 설정 |

## 3. 파트 1: AI Agent·판정 담당

목표는 **문구와 검색 근거를 받아 검수 결과·이유·수정안을 반환하는 것**입니다.

| 순서 | 작업 | 주요 파일 | 완료 기준 |
|---|---|---|---|
| 1 | 파트 2와 검색 응답·근거 충분성 기준 합의 | `schemas/review.py`, `graph/state.py` | 같은 근거 필드를 사용 |
| 2 | 실제 LLM 호출과 structured output 구현 | `graph/nodes/review_llm.py` | 모델 출력을 Pydantic으로 검증 |
| 3 | 근거 충분성·위험 여부·보류 판단 | `review_llm.py`, `graph/graph.py` | 세 상태를 의도대로 구분 |
| 4 | 수정안 생성 | `graph/nodes/generate_alternative.py` | 광고 목적을 유지하는 suggestion 생성 |
| 5 | 결과 검증 강화 | `graph/nodes/validate_result.py` | 인용·근거·상태 불일치를 탐지 |
| 6 | timeout·모델 오류 처리와 평가 | `api/routes/review.py`, `tests/` | 실패 상황과 평가셋 검증 |

판정 원칙:

- 금기어 hit만으로 `revise`를 확정하지 않고 광고 문맥을 함께 판단합니다.
- 근거 부족, 규칙과 근거의 충돌, 불확실한 판단은 `needs_review`로 보냅니다.
- 근거가 충분하고 위험이 확인되면 `revise`, 명확한 위험이 없으면 `pass`로 분기합니다.
- 역사·사회적 키워드가 있다는 이유만으로 위반이나 법적 판단을 단정하지 않습니다.
- `pass`도 최종 게시 승인으로 표현하지 않습니다.
- 근거 문서에 없는 내용을 `evidence`로 생성하지 않습니다.

실제 모델 연결 시 API key·모델명·timeout 설정을 추가하되, health와 mock 테스트에는
실제 key가 필요하지 않도록 유지합니다. 모델 테스트는 mock을 주입하고 실제 호출 평가와 구분합니다.

파트 1의 최소 산출물은 실제 판정 노드, 수정안 생성, 출력 검증, 세 상태·실패 상황 테스트와
평가 결과입니다. `trace_id`는 요청부터 로그·응답까지 유지합니다.

## 4. 파트 2: 데이터·검색·MCP 담당

목표는 **검수에 쓸 수 있는 근거를 출처와 함께 반환하는 것**입니다.

| 순서 | 작업 | 주요 위치 | 완료 기준 |
|---|---|---|---|
| 1 | 기준 데이터와 출처·버전 정리 | `rag-mcp/data/social/`, `data/corporate/` | 사용 가능한 문서와 metadata 확보 |
| 2 | 문서 분할과 임베딩 | `rag_mcp/retrieval/embeddings.py` | 선택한 모델로 vector 생성 |
| 3 | pgvector 적재·검색 | `rag_mcp/retrieval/vector_store.py` | 실제 관련 근거 검색, company_id 필터 |
| 4 | 두 검색 Tool 구현 | `rag_mcp/tools/` | 사회·역사 / 기업 가치 검색 결과 반환 |
| 5 | Agent 검색 노드 연결 | `ai-agent/app/clients/`, 검색 노드 두 개 | 조회 결과가 graph state에 들어감 |
| 6 | 실제 MCP 연결 | 각 `server.py`, Agent adapter | 지원 SDK·transport로 Tool 호출 확인 |
| 7 | 검색·기업 격리·오류 테스트 | `rag-mcp/tests/`, Agent 테스트 | 빈 결과·다른 기업·서버 실패 검증 |

RAG-MCP는 SDK v1.30.0의 실제 MCP `/mcp`와 REST 검색을 제공합니다.
기업 문서 업로드 API·컬럼·예시는 [RAG 가이드](rag-mcp/README.md)에 정리했습니다.
Business도 실제 MCP `/mcp`와 기존 HTTP 검색을 제공합니다. Agent는 아직 Business HTTP adapter를 사용합니다.
계약과 파트 1 연결 사항은 [Business 가이드](business-mcp/README.md)를 참조하세요.

실제 검색 전환에 필요했던 작업(`mock: false`, `company_id` 필터, 384차원 일치, Agent lifespan의 client·timeout,
async 검색 노드)은 완료했습니다. 남은 합의 사항은 다음과 같습니다.

- 기업 문서가 없거나 빈 결과인 경우, 이를 근거 충분으로 처리하지 않도록 파트 1과 합의합니다.
- BE가 검수 요청에 첨부 문서 ID(`context.document_ids`)를 보내도록 합의합니다.

외부검색 `search_recent_issue`는 Business 서버에 구현되어 있습니다.
검색어 생성·호출 정책은 파트 1이 연결하며, 상세는 [Business 가이드](business-mcp/README.md)에 있습니다.

## 5. 금기어 RDB는 누가 어떻게 연결하나

**금기어 저장소는 향후 RDB입니다. 현재 JSON은 초기 실행용 샘플입니다.**
RDB에 저장한다는 이유만으로 탐지 노드 전체를 MCP로 옮길 필요는 없습니다.

현재 [rule_filter.py](ai-agent/app/graph/nodes/rule_filter.py)는 다음 책임으로 나뉩니다.

```text
load_rules      규칙 데이터 로딩 (현재 JSON)
match_rules     정규화 + 활성 규칙 매칭
find_rule_hits  로딩과 매칭 조합
rule_filter    rule_hits를 LangGraph에 전달
```

권장 협업 구분은 다음과 같습니다. DB 소유권과 조회 방식은 아직 확정되지 않았습니다.

| 담당 | 할 일 |
|---|---|
| Backend / DB 담당 | RDB를 Backend가 관리한다면 테이블·규칙 CRUD·조회 API 제공 |
| 파트 2 | 선택된 RDB/API/MCP 조회 adapter 구현, 규칙 형식 변환 |
| 파트 1 | adapter를 rule_filter에 연결, 탐지 결과를 최종 문맥 판정에 반영 |

선택 가능한 구조:

- Backend 소유 RDB: `Agent → Backend 규칙 조회 API → RDB`
- AI 서비스 소유 RDB: `Agent → RDB 조회 adapter → RDB`
- 공통 Tool 재사용이 필요한 경우: `Agent → 금기어 MCP Tool → RDB`

우선 DB 소유 서비스, 조회 URL 또는 접속 방식, 규칙 ID·버전·필드, 실패 시 처리 기준을 합의합니다.
현재 필드인 `expression`, `category`, `severity`, `enabled`와 Agent 모델을 맞춰야 합니다.
네트워크 조회로 바꿀 때 `load_rules`만 async로 바꾸고 끝내지 말고 호출하는 노드까지 연결합니다.
규칙 조회 실패를 “금기어 없음”으로 처리하지 않도록 오류·보류 정책도 함께 정합니다.

## 6. 두 파트가 먼저 맞출 연동 계약

파트 2가 제공하는 현재 검색 함수 인터페이스:

```text
search_social_context(query)
search_corporate_value(query, company_id, document_ids=None)  # document_ids 지정 시 첨부 문서 전체 반환
search_recent_issue(query)  # Business MCP
```

사회·역사 검색은 `social_context_evidence`, 기업 가치 검색은 `corporate_value_evidence`에 넣습니다.
기업 가치 검색의 `company_id`는 Tool에서 필수지만 review 요청에서는 선택입니다.
누락 시 기본 기업을 사용할지, 기업 검토를 보류할지 두 파트가 합의해야 합니다.
현재 서버에 기본 기업 설정은 없습니다.

RAG 근거 레코드는 다음 필드를 보존합니다.

| 필드 | 의미 |
|---|---|
| `document` | 문서명 |
| `section` | 문서 항목 |
| `snippet` | 실제 검색된 근거 내용 |
| `rule_id` | 기준 ID |
| `version` | 기준 문서 버전. 적재 시 RAG가 자동 부여 |

RAG 근거는 5개 필드 모두 채워서 반환하며, Agent의 Evidence 모델은 `rule_id`, `version`을 선택으로 받습니다.
문서는 최신본만 두고 version은 내용이 바뀔 때 RAG가 자동으로 올립니다. 같은 광고를 다시 검수했을 때
어떤 판의 기준으로 판정했는지 이 값으로 추적합니다.
URL·점수 등 새 metadata가 필요하면 두 서비스의 모델을 함께 수정합니다.

공통 수정이 생기기 쉬운 파일은 `schemas/review.py`, `graph/state.py`, `graph/graph.py`,
설정과 requirements입니다. 변경 전에 필드·함수 계약을 맞추고 API 응답 호환성을 확인합니다.

## 7. 로컬에서 구동하기: venv + pip

아래 명령은 macOS / zsh 기준입니다. Python 3.12를 먼저 설치해야 합니다.
`.python-version`만으로 Python이 자동 설치되지는 않습니다.

### 7.1 최초 환경 구성

```bash
cd AdCheck-AI-MCP  # 저장소를 받은 위치에서
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp -n .env.example .env
```

실행 의존성만 필요하면 `python -m pip install -r requirements.txt`를 사용합니다.
테스트·Ruff를 실행할 개발 환경에는 `requirements-dev.txt`를 설치합니다.
현재 직접 의존성은 버전 고정, 간접 의존성은 pip가 호환되는 버전을 선택합니다.

이미 이 환경을 만들어 두었다면 매번 venv를 만들 필요는 없습니다.
새 터미널에서 저장소로 이동하고 `source .venv/bin/activate`만 실행하면 됩니다.

### 7.2 Agent만 실행

```bash
PYTHONPATH=ai-agent python -m app.main
```

- API 문서: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- 로컬 기본값 `RAG_RETRIEVAL_ENABLED=false`에서는 RAG에 연결하지 않아 Agent만 실행해도 review 요청이 됩니다.

### 7.3 RAG·Business 서버도 실행

별도 터미널 두 개에서 각각 저장소 루트로 이동하고 venv를 활성화한 뒤 실행합니다.
RAG는 pgvector DB가 필요합니다. DB 준비와 사회 문서 적재는 [RAG 가이드](rag-mcp/README.md) 3장을 따릅니다.
Agent가 실제 RAG를 호출하게 하려면 `.env`에서 `RAG_RETRIEVAL_ENABLED=true`로 바꾸고 Agent를 다시 시작합니다.

RAG:

```bash
python -m uvicorn rag_mcp.server:app --app-dir rag-mcp --host 0.0.0.0 --port 8001
```

Business:

```bash
python -m uvicorn business_mcp.server:app --app-dir business-mcp --host 0.0.0.0 --port 8002
```

서버 종료는 각 터미널에서 `Ctrl+C`, 가상환경 종료는 `deactivate`입니다.
Docker로 같은 포트의 서비스를 실행 중이면 먼저 `docker compose down`으로 중지합니다.

## 8. Docker Compose로 전체 구동

Docker Desktop을 켠 뒤 저장소 루트에서 실행합니다. 로컬 venv 활성화는 필요하지 않습니다.

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

| 서비스 | 호스트 포트 | 확인 URL |
|---|---:|---|
| Agent | 8000 | <http://localhost:8000/health> |
| RAG | 8001 | <http://localhost:8001/health> |
| Business | 8002 | <http://localhost:8002/health> |
| pgvector | 5433 | `docker compose exec pgvector pg_isready -U adcheck -d adcheck_rag` |

로그 확인과 종료:

```bash
docker compose logs --tail=100 ai-agent
docker compose logs -f ai-agent rag-mcp business-mcp
```

로그 추적을 끝내려면 `Ctrl+C`를 누릅니다. 백그라운드 서비스는 계속 실행됩니다.

```bash
docker compose down
```

pgvector 데이터는 named volume에 유지됩니다. `down -v`는 볼륨 데이터까지 삭제하므로
일반적인 종료에는 `down`을 사용합니다.
소스는 컨테이너에 복사되는 구조이므로 코드 변경 후에는 `up --build -d`로 다시 빌드합니다.
빈 DB에서는 사회 문서 적재 명령을 실행해야 합니다. `docker compose exec rag-mcp python -m rag_mcp.cli ingest-social`을 사용하고 기업 문서는 업로드 API로 등록합니다.

## 9. 환경변수 사용 방법

설정 예시는 [.env.example](.env.example)에 있고 실제 로컬 설정은 `.env`에 둡니다.
`.env`는 Git과 Docker build context에서 제외됩니다.

| 변수 | 현재 사용 방식 |
|---|---|
| `AI_AGENT_PORT` | 로컬 Agent 포트, Compose의 호스트 포트 |
| `RAG_MCP_PORT`, `BUSINESS_MCP_PORT`, `RAG_DB_PORT` | Compose의 호스트 포트 |
| `RAG_DB_USER`, `RAG_DB_PASSWORD`, `RAG_DB_NAME` | Compose pgvector 계정·DB 이름 |
| `RAG_MCP_URL`, `BUSINESS_MCP_URL` | Agent가 호출할 RAG·Business 주소 |
| `RAG_RETRIEVAL_ENABLED` | Agent의 실제 RAG 호출 여부. 로컬 기본 `false`, Compose `true` |
| `RAG_DATABASE_URL` | RAG 서비스의 pgvector 접속 주소 |
| `RAG_EMBEDDING_MODEL`, `RAG_MODEL_CACHE` | 임베딩 모델과 모델 파일 저장 위치 |
| `RAG_MAX_UPLOAD_BYTES`, `RAG_MAX_ROWS` | 기업 문서 업로드 크기·행 수 한도 |
| `RAG_MAX_ATTACHED_CHARS` | 첨부 문서 전체 반환 시 본문 합계 상한. 넘으면 `too_large` |
| `HTTP_TIMEOUT_SECONDS` | Agent의 RAG MCP 호출 timeout |
| `LOG_LEVEL` | Agent 로깅 수준 |
| `TAVILY_API_KEY`, `TAVILY_TIMEOUT_SECONDS`, `TAVILY_MAX_RESULTS` | Business 외부검색 key·시간·결과 수 제한 |

`RAG_MAX_*` 값은 Compose의 `environment`에 전달하지 않으므로 컨테이너에서는 기본값을 사용합니다.

로컬 프로세스끼리는 `localhost`, Compose 컨테이너끼리는 `rag-mcp`, `business-mcp`,
`pgvector` 서비스명을 씁니다. Compose에서는 이 내부 URL을 `environment`로 지정해 둡니다.
호스트 포트를 바꿔도 Compose 내부 서비스 포트는 8000 / 8001 / 8002 / 5432 그대로입니다.
RAG / Business 로컬 실행 포트는 `.env`가 아닌 위 명령의 `--port`로 지정합니다.

모델 key 등 새 변수를 추가할 때 `.env.example`, Settings, Compose의 `environment`도
함께 갱신합니다. 호스트의 `.env`에 쓰는 것만으로 모든 값이 컨테이너에 자동 전달되지는 않습니다.
설정 변경 후 서버를 재시작합니다.

## 10. API 호출과 Backend 연동

Backend가 호출할 API는 **`POST /api/v1/reviews`**입니다.
현재 이 저장소에는 결과 저장, 이력 조회, 재검수 전용 endpoint가 없습니다.
같은 API에 수정한 문구를 다시 보내면 새 `trace_id`로 검수합니다.

```bash
curl -fsS http://localhost:8000/health

curl -fsS http://localhost:8000/api/v1/reviews \
  -H 'Content-Type: application/json' \
  -d '{"text":"5월 18일을 기념해 오늘만 특별 할인! 탱크처럼 강력한 혜택을 만나보세요.","context":{"channel":"sns","campaign_name":"봄 프로모션","company_id":"company_demo"}}'
```

입력은 `text` 공백 제거 후 1~2,000자, `context.channel`은 필수 `sns`입니다.
`campaign_name`은 선택·최대 100자, `company_id`는 선택·제공 시 1~100자입니다.
`document_ids`는 선택이며, 첨부한 기업 문서 ID 1~100개를 주면 해당 문서 전체를 기업 근거로 사용합니다.
입력 오류는 현재 FastAPI 기본 HTTP 422 응답을 사용합니다.
Backend가 기대하는 오류 형식이 있다면 별도로 합의해 구현해야 합니다.

응답 계약은 [ReviewResponse](ai-agent/app/schemas/review.py)와 `/docs`를 기준으로 합니다.
`status`, `summary`, `findings`, `trace_id`를 유지합니다.
각 finding은 유형, 위험도, 원문, 이유, 근거, 선택 수정안, 사람 검토 필요 여부를 갖습니다.

RAG 검색 REST를 직접 확인하려면:

```bash
curl -fsS http://localhost:8001/tools/search_social_context \
  -H 'Content-Type: application/json' \
  -d '{"query":"사회적 맥락"}'

curl -fsS http://localhost:8001/tools/search_corporate_value \
  -H 'Content-Type: application/json' \
  -d '{"query":"윤리적 생산","company_id":"taegeon_beauty","document_ids":["taegeon_beauty-ethics_policy"]}'
```

결과는 `mock: false`입니다. 사회 문서를 적재하고 기업 문서를 업로드했다면 근거가 반환되고, 없으면 `status: empty`입니다.
Agent는 같은 Tool을 MCP `/mcp`로 호출합니다.

## 11. 테스트와 자주 막히는 부분

venv를 활성화한 상태로 저장소 루트에서 실행합니다.

```bash
python -m pip check
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

파트별 테스트만 실행할 수도 있습니다.

```bash
python -m pytest ai-agent/tests -q
python -m pytest rag-mcp/tests -q
python -m pytest business-mcp/tests -q
```

| 증상 | 확인할 점 |
|---|---|
| Python 버전이 3.11 등으로 나옴 | `python3.12 -m venv .venv`로 만들었는지와 venv 활성화 확인 |
| 패키지를 찾지 못함 | 활성화 후 `python -m pip install -r requirements-dev.txt` 실행 |
| `No module named app` | 저장소 루트에서 `PYTHONPATH=ai-agent python -m app.main` 실행 |
| 포트 사용 중 | Docker와 로컬 프로세스가 같은 포트를 사용하는지 확인 |
| Docker daemon 연결 실패 | Docker Desktop 실행 상태 확인 |
| 변경 코드가 Docker에 반영되지 않음 | `docker compose up --build -d`로 재빌드 |
| 금기어를 넣어도 `needs_review` | 현재 LLM mock의 의도된 동작. 규칙 hit와 API findings는 별개 |
| pgvector는 켜졌지만 근거가 비어 있음 | 사회 문서 적재 여부, 기업 ID와 업로드 문서, `document_ids` 확인 |

## 12. 다음 작업의 진행 순서

1. 두 파트와 Backend가 금기어 DB 소유권·조회 계약, 근거 schema, 기업 ID 정책을 합의합니다.
2. 파트 1은 합의한 근거 fixture로 판정·수정안·검증을 구현합니다.
3. 파트 2는 기준 문서 준비부터 실제 RAG 검색을 구현합니다. **(완료)**
4. 파트 2의 adapter와 파트 1의 그래프를 연결하고 mock 표시를 실제 기능에 맞게 교체합니다. **(RAG 완료, 판정은 mock)**
5. 선택한 MCP SDK로 서버·클라이언트를 연결하고 실제 Tool 호출을 검증합니다. **(RAG 완료, Business는 Agent client 전환 남음)**
6. 금기어 RDB/API를 연결하고 실패·보류 처리를 검증합니다.
7. Backend에서 review API를 호출해 end-to-end로 확인합니다.
8. 정상·수정·보류·오류 사례와 20건 이상 평가셋으로 동작을 확인합니다.

각 단계에서는 API key 없는 health와 기존 mock 단위 테스트를 유지합니다.
외부검색, 이력 저장, 인증 등 범위 확장 기능은 현재 필수 연결을 마친 뒤 별도로 결정합니다.
