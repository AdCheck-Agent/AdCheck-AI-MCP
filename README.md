# AdCheck AI MCP

SNS 광고 문구의 사회·역사적 논란 가능성을 검토하는 AI 서비스의 초기 골격입니다.
Python 3.12, FastAPI, Pydantic v2, LangGraph, httpx를 사용하며, venv + pip로 환경을 관리합니다.
Spring Boot Backend와 Frontend는 별도 프로젝트이며 이 저장소에 포함하지 않습니다.

**현재 실제 RAG·LLM 검수는 수행하지 않습니다.** API key 없이 실행되며, 검수 API는
`[MOCK]` 요약과 `needs_review`를 반환합니다. 근거가 없는 상태에서 통과나 위반을 확정하지 않습니다.

## 서비스 구성

| 서비스 | 기본 포트 | 현재 역할 |
|---|---:|---|
| ai-agent | 8000 | 입력 검증, 금기어 필터, LangGraph, 응답 검증 |
| rag-mcp | 8001 | 사회·역사 / 기업 가치 검색 HTTP placeholder |
| business-mcp | 8002 | 외부검색 HTTP placeholder; 실제 검색은 보류 |
| qdrant | 6333 | 공식 이미지, 데이터 볼륨; 아직 검색·적재 미연결 |

`rag-mcp`와 `business-mcp`는 **MCP 프로토콜 서버가 아닙니다.** 현재는 FastAPI의
HTTP Tool 인터페이스입니다. MCP SDK에 대한 추측을 피하고, 추후 검증된 SDK 및 transport로
교체할 수 있도록 Tool 함수와 Agent의 Protocol / HTTP adapter를 분리했습니다.
현재 그래프는 adapter를 호출하지 않아 세 서비스가 각각 독립 실행됩니다.

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
│   │   │       ├── review_llm.py
│   │   │       ├── generate_alternative.py
│   │   │       ├── decide_result.py
│   │   │       └── validate_result.py
│   │   ├── clients/{rag_mcp_client,business_mcp_client}.py
│   │   └── rules/banned_expressions.json
│   ├── tests/{test_api,test_rules,test_graph}.py
│   └── Dockerfile
├── rag-mcp/
│   ├── rag_mcp/
│   │   ├── server.py
│   │   ├── schemas.py
│   │   ├── tools/{search_social_context,search_corporate_value}.py
│   │   └── retrieval/{vector_store,embeddings}.py
│   ├── data/{social,corporate}/.gitkeep
│   ├── tests/test_rag_service.py
│   └── Dockerfile
├── business-mcp/
│   ├── business_mcp/
│   │   ├── server.py
│   │   ├── schemas.py
│   │   └── tools/search_recent_issue.py
│   ├── tests/test_business_service.py
│   └── Dockerfile
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
cd ~/Desktop/skala-projects/AI-Mini-Project/AdCheck-AI-MCP
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

`.env`는 Git과 Docker build context에서 제외됩니다. API key 설정은 없습니다.
로컬 `.env`의 URL은 `localhost`이며, Compose는 컨테이너 통신 URL을 서비스명으로 덮어씁니다.
`HTTP_TIMEOUT_SECONDS`는 향후 HTTP client 생성 시 사용할 설정입니다.
`QDRANT_URL`은 추후 Retriever 구현용 예약 설정이며 현재 사용하지 않습니다.

## 로컬 실행

저장소 루트에서 각각 별도의 터미널로 실행합니다.

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
- 입력 오류: FastAPI 기본 `422` validation response

현재 응답 예시 (`trace_id`는 요청마다 새로 생성):

```json
{
  "status": "needs_review",
  "summary": "[MOCK] 실제 RAG·LLM 검수를 수행하지 않았습니다. 근거 확인과 사람 검토가 필요합니다.",
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
- Retriever / Embeddings Protocol, HTTP Tool 함수와 클라이언트 인터페이스
- Dockerfile 3개와 Qdrant 공식 이미지를 사용하는 Compose

Mock / 미구현:

- 사회·역사 / 기업 가치 retrieval: 빈 근거 반환, 데이터 수집·임베딩·적재 없음
- LLM 판단: API 호출 없이 근거 부족과 불확실을 설정
- 대안 생성: 분기와 TODO만 존재하며 실제 suggestion 생성 없음
- MCP protocol, 외부검색: 미구현; HTTP tool 응답에 `mock: true` 표시
- Output Validator: 현재는 schema만 검사; 근거 출처 / 인용 검증은 후속 작업

규칙 hit를 실제 근거처럼 꾸미지 않아 현재 API의 `findings`는 비어 있습니다.
`pass` / `revise` 분기는 테스트 전용 reviewer로 검증하며 운영 mock API에서는 도달하지 않습니다.
`pass`는 최종 게시 승인이나 법률 판단을 뜻하지 않습니다.

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

Qdrant 데이터는 `qdrant-data` named volume에 유지합니다. RAG가 아직 Qdrant를 사용하지 않으므로
검색 서비스 시작에 Qdrant readiness 의존성은 두지 않았습니다.
Docker build context는 루트이고, 각 서비스는 자기 소스만 복사하여 독립 프로세스로 실행합니다.
각 Dockerfile은 루트 `requirements.txt`를 pip로 설치합니다. 개발 도구는 이미지에 포함하지 않습니다.

## 테스트와 코드 품질

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

실제 LLM / 외부 API를 호출하지 않습니다. API 입력·응답, JSON 규칙,
그래프 모든 결과 분기와 END 도달, Tool / client 계약을 검증합니다.

초기 세팅 확인 결과:

- Python 3.12 venv + pip 환경, requirements 파일로 의존성 설치
- pytest: 26개 통과
- Ruff lint / format 검사 통과
- Docker Compose config 검증 완료
- Docker Compose build / up 완료, 서비스 4개 실행 확인
- 컨테이너 간 HTTP 통신: Agent / RAG / Business health 및 Qdrant healthz 모두 200
- 실제 실행 중인 Agent의 `POST /api/v1/reviews`: 200, mock `needs_review` 응답 확인

## 다음 작업 / 담당 제안

**AI 1 — Agent / 판정**

- `review_llm.py`: 모델 provider 설정, structured output, 문맥 판단, 근거 충분성 판정
- 규칙과 검색 결과 충돌, 기업 자료 부족, 불확실성은 `needs_review`로 처리
- `generate_alternative.py`: 광고 의도를 유지하는 수정안 생성
- `validate_result.py`: 원문 인용 범위, 실제 검색 근거 및 상태·findings 일관성 검증
- 모델 timeout / 실패 처리, 평가셋과 회귀 테스트

**AI 2 — 데이터 / 검색 / MCP**

- 승인된 합성 / 공개 기준 데이터와 출처·버전 메타데이터 설계
- 문서 분할, Embeddings 구현, Qdrant 적재 / 검색, 기업별 metadata 필터
- `search_social_context`, `search_corporate_value` 실제 구현
- MCP SDK의 지원 API / transport 확인 후 서버·클라이언트 adapter 교체
- Agent retrieval node에 client lifecycle / 설정 / timeout 주입
- 외부검색은 후속 범위 확정 후 구현하며 현재는 보류

참고한 LangGraph API: [StateGraph 공식 문서](https://reference.langchain.com/python/langgraph/graph/state/StateGraph).
Qdrant 이미지 태그: [공식 v1.15.5 릴리스](https://github.com/qdrant/qdrant/releases/tag/v1.15.5).
