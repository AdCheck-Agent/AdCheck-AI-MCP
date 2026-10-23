# AdCheck AI MCP

SNS 광고 문구의 사회·역사적 논란 가능성과 기업 가치와의 불일치를 검토하는 AI 서비스입니다.
Python 3.12, FastAPI, Pydantic v2, LangGraph, httpx를 사용하며, venv + pip로 환경을 관리합니다.
Spring Boot Backend와 Frontend는 별도 프로젝트이며 이 저장소에 포함하지 않습니다.

**RAG 적재·검색과 Business 외부검색은 실제로 동작하고, Agent는 설정에 따라 실제 RAG를 호출합니다. LLM 판정은 아직 mock입니다.** API key 없이 실행되며, mock 검수 실행 결과는
`[MOCK]` 요약과 `needs_review`를 반환합니다. 근거가 없는 상태에서 통과나 위반을 확정하지 않습니다.

## 서비스 구성

| 서비스 | 기본 포트 | 현재 역할 |
|---|---:|---|
| ai-agent | 8000 | 입력 검증, 금기어 필터, LangGraph, 응답 검증 |
| rag-mcp | 8001 | pgvector 검색, CSV/XLSX 기업 문서 처리, 실제 MCP |
| business-mcp | 8002 | Tavily 외부검색 MCP·HTTP, 상세는 별도 가이드 |
| pgvector | 5433 | PostgreSQL 18 / vector(1024), 기업별 문서·chunk 저장 |

`rag-mcp`는 실제 MCP `/mcp`와 검색·문서 관리 REST API를 제공합니다.
구현·실행·업로드 컬럼은 [RAG 가이드](rag-mcp/README.md)를 확인하세요.
Business 외부검색의 별도 구현 내용은 [Business 가이드](business-mcp/README.md)를 확인하세요.
Compose에서는 Agent의 실제 MCP 검색이 켜집니다. 로컬은 RAG_RETRIEVAL_ENABLED=true로 활성화합니다.

## 디렉터리 구조

```text
.
├── ai-agent/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes/{health,review}.py
│   │   ├── core/{config,logging}.py
│   │   ├── schemas/review.py
│   │   ├── graph/
│   │   │   ├── state.py
│   │   │   ├── graph.py
│   │   │   └── nodes/
│   │   │       ├── rule_filter.py
│   │   │       ├── retrieve_social_context.py
│   │   │       ├── retrieve_corporate_value.py
│   │   │       ├── retrieve_external_evidence.py
│   │   │       ├── review_llm.py
│   │   │       ├── generate_alternative.py
│   │   │       ├── decide_result.py
│   │   │       └── validate_result.py
│   │   ├── clients/{rag_mcp_client,business_mcp_client}.py
│   │   └── rules/banned_expressions.json
│   ├── tests/{test_api,test_rules,test_graph,test_rag_nodes,test_external_search}.py
│   └── Dockerfile
├── rag-mcp/
│   ├── rag_mcp/
│   │   ├── server.py
│   │   ├── schemas.py
│   │   ├── documents.py   # CSV/XLSX·사회 문서 해석과 분할
│   │   ├── cli.py         # init-db, ingest-social
│   │   ├── evaluation.py  # 실제 임베딩 검색 품질 평가
│   │   ├── schema.sql
│   │   ├── tools/{search_social_context,search_corporate_value}.py
│   │   └── retrieval/{vector_store,embeddings}.py
│   ├── data/  # 사회 기준·사례, 두 기업 문서, 출처·적재 목록
│   ├── tests/  # 문서·pgvector·MCP·평가·서비스 테스트
│   └── Dockerfile
├── business-mcp/
│   ├── business_mcp/
│   │   ├── server.py
│   │   ├── schemas.py
│   │   ├── config.py
│   │   ├── clients/tavily_client.py
│   │   └── tools/search_recent_issue.py
│   ├── tests/{test_business_service,test_tavily_client,test_mcp_transport}.py
│   └── Dockerfile
├── docs/  # 작업 기록·파트 1 전달 사항·검색 평가 결과
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── .python-version
├── .env.example
├── .gitignore
├── .dockerignore
└── README.md
```

각 Python 패키지에 `__init__.py`를 배치했습니다.
RAG / Business는 import 충돌을 피하도록 `rag_mcp` / `business_mcp` 패키지를 사용합니다.

## 환경 구성

Python 3.12를 먼저 설치한 뒤 저장소 루트에서 실행합니다.
`.python-version`은 버전 안내 파일이며 venv가 Python을 자동 설치하지는 않습니다.

```bash
cd AdCheck-AI-MCP  # 저장소를 받은 위치에서
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp -n .env.example .env
```

`requirements.txt`는 실행 의존성, `requirements-dev.txt`는 실행 의존성과 테스트·Ruff를 포함합니다.
직접 의존성 버전은 고정하며, 간접 의존성은 pip가 각 패키지 요구사항에 맞춰 설치합니다.
`pyproject.toml`에는 pytest / Ruff 설정만 유지합니다.
새 터미널마다 저장소 루트에서 `source .venv/bin/activate`를 실행하세요.
환경을 종료할 때는 `deactivate`를 사용합니다.

`.env`는 Git과 Docker build context에서 제외됩니다.
API key는 Business 외부검색의 `TAVILY_API_KEY`만 사용하며, 비워 두면 외부검색이 `unavailable`을 반환합니다.
로컬 `.env`의 URL은 `localhost`이며, Compose는 컨테이너 통신 URL을 서비스명으로 덮어씁니다.
`HTTP_TIMEOUT_SECONDS`는 Agent의 RAG MCP 호출 timeout입니다.
`RAG_DATABASE_URL`은 RAG 서비스의 pgvector 접속 설정입니다. 전체 변수는 [가이드](guide.md) 9장을 참고하세요.

## 로컬 실행

저장소 루트에서 각각 별도의 터미널로 실행합니다.
RAG는 pgvector DB와 사회 문서 적재가 먼저 필요합니다([RAG 가이드](rag-mcp/README.md) 3장).
Agent가 실제 RAG를 호출하게 하려면 `.env`의 `RAG_RETRIEVAL_ENABLED=true`로 설정합니다.

```bash
PYTHONPATH=ai-agent python -m app.main
```

```bash
python -m uvicorn rag_mcp.server:app --app-dir rag-mcp --host 0.0.0.0 --port 8001
```

```bash
python -m uvicorn business_mcp.server:app --app-dir business-mcp --host 0.0.0.0 --port 8002
```

Agent의 포트는 `.env`의 `AI_AGENT_PORT`로 변경합니다. RAG / Business 로컬 포트는
위 `--port` 값으로 지정합니다. 이 두 서비스의 `.env` 포트 값은 Compose의 호스트 포트에 적용됩니다.
각 서비스의 `/docs`에서 OpenAPI를 확인할 수 있습니다.

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8001/health
curl -fsS http://localhost:8002/health
curl -fsS http://localhost:8000/api/v1/reviews \
  -H 'Content-Type: application/json' \
  -d '{"text":"5월 18일을 기념해 오늘만 특별 할인! 탱크처럼 강력한 혜택을 만나보세요.","context":{"channel":"sns","campaign_name":"봄 프로모션","company_id":"company_demo"}}'
```

## Spring Boot 연동 계약

Backend는 AI Agent의 `POST http://localhost:8000/api/v1/reviews`를 JSON으로 호출합니다.
Agent는 **HTTP 202 접수 응답을 먼저 전송하고 FastAPI BackgroundTasks에서 검수를 실행**합니다.
Spring은 전체 검수 실행이 끝날 때까지 이 요청의 응답을 기다리지 않습니다.
컨테이너 / 원격 환경에서는 실제 Agent 주소를 설정합니다. Backend 컨테이너 내부의
`localhost`는 Backend 자신이므로 Agent 주소로 사용하면 안 됩니다.

```json
{
  "text": "새로운 상품을 소개합니다.",
  "context": {
    "channel": "sns",
    "campaign_name": "봄 프로모션",
    "company_id": "company_demo"
  }
}
```

- `text`: 앞뒤 공백 제거 후 1~2,000자
- `context.channel`: 필수, `sns`만 허용
- `campaign_name`: 선택, 최대 100자
- `company_id`: 선택, 제공 시 1~100자. 현재 기본 기업은 지정하지 않습니다.
- `document_ids`: 선택, 이번 검수에 첨부해 RAG 업로드가 끝난 기업 문서 ID 1~100개.
  주면 해당 문서 전체를 기업 근거로 사용하고, 없으면 기업 전체에서 유사도 검색합니다.
- 입력 오류: FastAPI 기본 `422` validation response

접수 응답 예시 (HTTP 202, `trace_id`는 요청마다 새로 생성):

```json
{
  "status": "accepted",
  "trace_id": "trace_0123456789abcdef0123456789abcdef"
}
```

작업 ID, 상태 조회 API, SQLite 작업 저장소는 사용하지 않습니다.
검수 실행·결과 검증은 `app/services/review.py`의 `run_review`에서 수행합니다.
최종 결과 전달용 SSE는 다른 브랜치에서 별도로 연결하며, 이 변경에 SSE 구현을 포함하지 않습니다.
BackgroundTasks의 반환값은 HTTP로 자동 전송되지 않으므로 해당 브랜치에서 결과 전달을 연결해야 합니다.

완료 상태·시간 초과·실행 오류는 `trace_id`와 함께 로그에 남깁니다.
이미 202를 전송했으므로 실행 오류를 같은 요청의 HTTP 500/504로 반환하지 않습니다.
`REVIEW_TIMEOUT_SECONDS`는 백그라운드 검수의 제한 시간으로 기본 60초입니다.
실행은 서버 프로세스 내부에서 이루어지며, 재시작 후 작업 복구는 제공하지 않습니다.

검수 실행 결과 구조 예시 (접수 응답과 별개):

```json
{
  "status": "needs_review",
  "summary": "[MOCK] LLM 판정은 아직 구현하지 않았습니다. 검색 여부와 별개로 사람 검토가 필요합니다.",
  "findings": [],
  "trace_id": "trace_0123456789abcdef0123456789abcdef"
}
```

실제 검수로 교체할 때도 상태는 `pass | revise | needs_review`를 유지합니다.
`findings` 항목은 `category`, `severity` (`low | medium | high`), `quote`, `reason`,
`evidence` (`document`, `section`, `snippet`, 선택 `rule_id`, `version`),
`suggestion` (선택), `needs_human_review`로 구성합니다.
Pydantic 모델과 `/docs`의 schema가 계약의 기준입니다.
기획안의 Backend 전용 `review_id`, 이력 조회, 재검수, 저장소, 오류 envelope는 이번 범위에 포함하지 않습니다.

## 금기어 RDB 연동 방향

현재 JSON은 초기 실행용 샘플입니다. RDB 연동은 아직 구현하지 않았습니다.
RDB에 저장한다고 반드시 MCP로 옮길 필요는 없습니다. 데이터 저장 위치와 접근 방식은 별도 결정입니다.

- `rules/banned_expressions.json`: 임시 규칙 데이터
- `graph/nodes/rule_filter.py`의 `load_rules`: 현재 JSON 로딩; 향후 RDB / API 조회로 교체할 경계
- 같은 파일의 `match_rules`: 저장소와 무관하게 정규화·활성 규칙 매칭 수행
- `rule_filter`: 탐지 결과를 그래프 상태에 전달하며 최종 판정은 하지 않음

금기어 RDB를 Spring Boot가 관리한다면 Backend의 규칙 조회 API를 Agent가 호출하는 구조가
간단합니다. AI 서비스가 RDB를 소유한다면 Agent에서 직접 조회할 수도 있습니다.
여러 Agent가 공통 Tool로 재사용해야 할 때 MCP에 `search_banned_expressions`를 제공하는 방식을
선택할 수 있습니다. DB 소유 서비스와 조회 계약이 정해지면 실제 adapter를 구현합니다.
현재 `rag-mcp`는 문서 검색, `business-mcp`는 외부검색 역할을 유지합니다.

## 검수 흐름과 mock 범위

```text
START → rule_filter → retrieve_social_context → retrieve_corporate_value → review_llm
  ├─ RAG 검색 실패 → mark_needs_review
  ├─ 근거 부족 + 판정 노드의 검색어 있음 + 외부검색 미시도 → external_search → review_llm (재판정)
  ├─ 근거 부족 / 불확실 → mark_needs_review
  ├─ 근거 충분 + 위험 있음 → generate_alternative (revise)
  └─ 근거 충분 + 위험 없음 → mark_pass
모든 분기 → validate_result → END
```

실제 구현된 기능:

- FastAPI health / review API, 입력 및 출력 Pydantic 검증
- JSON 규칙: Unicode NFKC, 대소문자 및 공백 정규화, 활성 규칙 검색
- 규칙 필터는 hit만 반환하며 최종 판정은 하지 않음
- 요청별 상태 / trace_id, LangGraph compile 및 sync / async 실행
- 최소 로그에는 trace_id와 상태만 기록
- RAG: pgvector 검색, 기업 격리, 첨부 문서 전체 반환, MCP `/mcp`, Agent의 RAG MCP client
- Business: Tavily 외부검색 MCP `/mcp`·HTTP, 검수당 1회 외부검색 분기
- Dockerfile 3개와 PostgreSQL 18 pgvector 이미지를 사용하는 Compose

Mock / 미구현:

- RAG 적재·검색과 Agent 노드 연결 구현됨. 로컬 기본 설정은 오프라인이며 Compose는 실제 검색 활성화
- LLM 판단: API 호출 없이 근거 부족과 불확실을 설정
- 대안 생성: 분기와 TODO만 존재하며 실제 suggestion 생성 없음
- RAG·Business MCP 서버 구현됨. Business의 Agent client는 아직 HTTP 사용
- Output Validator: 현재는 schema만 검사; 근거 출처 / 인용 검증은 후속 작업

규칙 hit를 실제 근거처럼 꾸미지 않아 현재 API의 `findings`는 비어 있습니다.
`pass` / `revise` 분기는 테스트 전용 reviewer로 검증하며 운영 mock API에서는 도달하지 않습니다.
`pass`는 최종 게시 승인이나 법률 판단을 뜻하지 않습니다.

## 준비된 RAG 문서

[데이터 안내](rag-mcp/data/README.md)에 사회·역사 검수 기준 6개, 확인한 사례 6개,
태건뷰티·서준로스터스의 기업 문서 각 3개를 정리했습니다.
기관 사실·보도 내용·프로젝트 검수 기준을 구분하고 출처 12개를 기록했습니다.
미확인 사례는 적재 대상에서 제외합니다.
사회 문서 적재는 `python -m rag_mcp.cli ingest-social`로 수행합니다. 기업 샘플은 CSV/XLSX 3종이며 자동 적재하지 않습니다.

## Docker Compose

Docker daemon (예: Docker Desktop)이 실행 중이어야 합니다.
이미지 빌드 때 Python 이미지와 패키지 다운로드를 위한 네트워크가 필요합니다.

```bash
docker compose config --quiet
docker compose up --build
```

중지:

```bash
docker compose down
```

pgvector 데이터는 `rag-postgres`, 모델 캐시는 `rag-models` named volume에 유지합니다.
RAG는 DB readiness 확인 후 전용 schema를 초기화합니다. 기존 Qdrant 볼륨은 자동 삭제하지 않습니다.
Docker build context는 루트이고, 각 서비스는 자기 소스만 복사하여 독립 프로세스로 실행합니다.
공통 의존성은 루트 requirements, RAG 추가 의존성은 rag-mcp/requirements.txt를 pip로 설치합니다. 개발 도구는 이미지에 포함하지 않습니다.

## 테스트와 코드 품질

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

실제 LLM / 외부 API를 호출하지 않습니다. API 입력·응답, JSON 규칙,
그래프 모든 결과 분기와 END 도달, Tool / client 계약을 검증합니다.

DB 통합 테스트는 `RAG_TEST_DATABASE_URL`에 `_test`로 끝나는 전용 DB를 지정해야 실행됩니다([RAG 가이드](rag-mcp/README.md) 8장).

최근 확인 결과 (2026-10-23):

- pytest 127개 통과 (전용 test DB 포함. DB 없이 실행하면 119개 통과·8개 건너뜀), Ruff lint 통과
- 실제 임베딩 검색 평가: 사회 hit@1 0.80·MRR 0.87, 전체 hit@5 0.90, 기업 격리 위반 0건
- Docker Compose `up --build`: 4개 서비스 healthy, 사회 문서 적재·기업 문서 업로드, Agent 검수 요청 → RAG MCP → pgvector 확인

## 다음 작업 / 담당 제안

**AI 1 — Agent / 판정**

- `review_llm.py`: 모델 provider 설정, structured output, 문맥 판단, 근거 충분성 판정
- 규칙과 검색 결과 충돌, 기업 자료 부족, 불확실성은 `needs_review`로 처리
- `generate_alternative.py`: 광고 의도를 유지하는 수정안 생성
- `validate_result.py`: 원문 인용 범위, 실제 검색 근거 및 상태·findings 일관성 검증
- 모델 timeout / 실패 처리, 평가셋과 회귀 테스트

**AI 2 — 데이터 / 검색 / MCP**

- 완료: 기준 데이터·출처·자동 version, pgvector 적재·검색, CSV/XLSX 업로드, RAG MCP 서버·client,
  Agent 검색 노드 연결, 첨부 문서 전체 반환, 실제 임베딩 검색 평가·허브 조각 개선, Tavily 외부검색 MCP·HTTP
- 남은 일: BE의 `document_ids` 전달 연결, 실제 광고 문구 형태의 평가 문항 확충
- 파트 1 연결: 외부검색 검색어 생성·호출 정책, Business의 Agent MCP client 전환

참고한 LangGraph API: [StateGraph 공식 문서](https://reference.langchain.com/python/langgraph/graph/state/StateGraph).
벡터 저장소: [pgvector 공식 문서](https://github.com/pgvector/pgvector).
