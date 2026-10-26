# AdCheck AI MCP

SNS 광고 문구의 사회·역사적 논란 가능성과 기업 가치와의 불일치를 검토하는 AI 서비스입니다.
Python 3.12, FastAPI, Pydantic v2, LangGraph, httpx, MCP SDK를 사용하며, venv + pip로 환경을 관리합니다.
Spring Boot Backend(AdCheck-BE)와 Frontend(AdCheck-FE)는 별도 저장소입니다.

**표현 신호 탐지, RAG 검색, LLM 의미 판정, 수정안 생성, 출력 검증, 외부검색, BE 체크포인트 보고가 동작합니다.**
금기어 사전 포함 검색은 BE가 담당하며 Agent의 표현 목록은 의미 검토의 참고 신호입니다. Agent 지적은 모두 `SEMANTIC`으로 전달합니다.
`OPENAI_API_KEY`를 비우면 모델을 호출하지 않고 `[MOCK]` 요약과 `needs_review`를 반환합니다.

## 서비스 구성

| 서비스 | 기본 포트 | 역할 |
|---|---:|---|
| ai-agent | 8000 | 검수 접수(HTTP 202), LangGraph 파이프라인, LLM 판정·수정안·검증, 단계 보고 |
| rag-mcp | 8001 | 사회·기업 근거 검색(MCP), 기업 CSV/XLSX 업로드 REST, pgvector |
| business-mcp | 8002 | Tavily 외부검색 `search_recent_issue`, BE 체크포인트 저장 `save_checkpoint` |
| pgvector | 5433 | PostgreSQL 18 + pgvector, `vector(1024)` (bge-m3) |

```text
FE ─JWT─▶ BE(Spring) ──PUT 기업 문서──▶ rag-mcp
               │ ──POST /api/v1/reviews──▶ ai-agent (202 accepted)
               │                              ├─ rag-mcp (MCP): 사회·기업 근거
               │                              ├─ business-mcp (MCP): 필요 시 외부검색
               │◀─PATCH /api/v1/reviews/checkpoint── business-mcp ◀─ 단계 완료·최종 결과
FE ◀─SSE─ BE
```

상세 문서:

- [guide.md](guide.md): 현재 상태, 파트별 담당, 실행·환경변수·연동 기준
- [RAG 가이드](rag-mcp/README.md): 업로드 형식(7개 컬럼), 검색 계약, Supabase 연결
- [Business 가이드](business-mcp/README.md): 외부검색·체크포인트 Tool
- [BE ↔ AI API 정리](docs/2026-10-23-backend-api-handoff.md)
- [금기어·의미 검토와 원문 위치 계약](docs/2026-10-26-review-spans.md)
- [검색 품질 평가](docs/2026-10-22-rag-retrieval-eval.md), [판정 평가셋](ai-agent/evaluation/README.md)

## 디렉터리 구조

```text
.
├── ai-agent/
│   ├── app/
│   │   ├── main.py                  # 시작 시 모델·MCP client·그래프 생성
│   │   ├── api/routes/{health,review}.py
│   │   ├── services/review.py       # 202 이후 백그라운드 검수 실행
│   │   ├── checkpoint.py, events.py # 단계 이벤트 → BE 체크포인트
│   │   ├── core/{config,logging}.py
│   │   ├── schemas/review.py        # BE와 공유하는 입력·결과 모델
│   │   ├── graph/{state,graph}.py, graph/nodes/
│   │   ├── llm/{judge,alternative,criteria,evidence,client,openai_model}.py
│   │   ├── clients/{rag_mcp_client,business_mcp_client}.py
│   │   └── rules/banned_expressions.json
│   ├── evaluation/                  # 판정 평가셋 v3, 기능 테스트(TC-01~08)
│   ├── tests/
│   └── Dockerfile
├── rag-mcp/
│   ├── rag_mcp/{server,schemas,documents,cli,evaluation}.py, schema.sql
│   ├── rag_mcp/tools/, rag_mcp/retrieval/{vector_store,embeddings}.py
│   ├── data/                        # 사회 기준·사례 12개, 예시 기업 2곳 × 3종
│   ├── tests/
│   └── Dockerfile
├── business-mcp/
│   ├── business_mcp/{server,schemas,config}.py, clients/tavily_client.py
│   ├── business_mcp/tools/{search_recent_issue,save_checkpoint}.py
│   ├── tests/
│   └── Dockerfile
├── docs/                            # 인계·평가 기록
├── docker-compose.yml, pyproject.toml, requirements*.txt, .env.example
└── README.md, guide.md
```

## 환경 구성

Python 3.12를 먼저 설치한 뒤 저장소 루트에서 실행합니다.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp -n .env.example .env
```

`.env`는 Git과 Docker build context에서 제외됩니다. 주요 key는 다음과 같습니다.

| 변수 | 비우면 |
|---|---|
| `OPENAI_API_KEY` | 판정·수정안 모델을 호출하지 않고 `[MOCK]` `needs_review` |
| `TAVILY_API_KEY` | 외부검색이 `unavailable` |
| `CHECKPOINT_ENABLED`, `ADCHECK_BE_BASE_URL`, `INTERNAL_API_KEY` | BE에 진행·결과를 보고하지 않음 |

전체 변수는 [guide.md](guide.md) 9장을 참고하세요.

## 실행

Docker Compose로 전체를 실행하는 것을 권장합니다.

```bash
docker compose up --build -d
docker compose ps                                              # 4개 healthy
docker compose exec rag-mcp python -m rag_mcp.cli ingest-social # 빈 DB일 때 한 번
```

처음 실행하면 bge-m3 모델(약 2.3GB)을 `rag-models` 볼륨에 내려받습니다.
컨테이너 시작 직후 첫 검색은 모델 로드로 10초 이상 걸릴 수 있으므로 미리 한 번 호출해 둡니다.

```bash
curl -s localhost:8001/tools/search_social_context -H 'Content-Type: application/json' -d '{"query":"준비"}' >/dev/null
```

로컬 Python 실행, 로그, 종료는 [guide.md](guide.md) 7·8장을 참고하세요.

## BE 연동 요약

1. BE가 첨부 CSV를 `PUT /api/v1/companies/{company_id}/documents/{document_id}`로 rag-mcp에 올립니다.
   기업·문서 ID는 URL에서 받고 파일에는 적지 않습니다.
2. BE가 `POST /api/v1/reviews`로 검수를 요청하면 Agent는 바로 `202 {"status":"accepted","trace_id":...}`를 반환합니다.
3. Agent는 백그라운드에서 검수하고, 단계가 끝날 때마다 business-mcp `save_checkpoint`로 BE에 보고합니다.
   마지막 `COMPLETED` 체크포인트에 최종 결과(`ReviewResponse`)가 들어갑니다.

```json
{
  "text": "5·18 탱크데이! 책상에 탁 치면 억 소리 나는 할인",
  "context": {"channel": "sns", "company_id": "<기업 ID>", "document_ids": ["<업로드한 문서 ID>"]},
  "review_id": "<original_text_id (UUID)>"
}
```

최종 결과:

```json
{
  "status": "revise",
  "summary": "5·18과 관련된 표현이 포함되어 있어 검토가 필요합니다.",
  "findings": [
    {
      "detection_type": "SEMANTIC",
      "category": "historical_context",
      "severity": "high",
      "quote": "5·18 탱크데이!",
      "reason": "5·18 민주화운동과 관련된 표현으로 상업적 활용이 논란이 될 수 있습니다.",
      "evidence": [{"document": "스타벅스 2026년 5월 행사명·문구 논란", "section": "보도에서 확인한 사실",
                    "snippet": "...", "rule_id": "CASE-HIST-001", "version": "v1", "source": "social"}],
      "suggestion": "특별 할인 이벤트!",
      "needs_human_review": false
    }
  ],
  "related_criteria": ["역사적 사건·기념일의 상업적 연상 활용"],
  "missing_information": [],
  "trace_id": "trace_0123456789abcdef0123456789abcdef"
}
```

입력·결과 필드, 오류, 합의 사항은 [BE ↔ AI API 정리](docs/2026-10-23-backend-api-handoff.md)를 기준으로 합니다.

## 검수 흐름

```text
START → rule_filter → retrieve_social_context → retrieve_corporate_value → review_llm
  ├─ RAG 검색 실패 → mark_needs_review
  ├─ 근거 부족 + 판정 노드의 검색어 + 외부검색 미시도 → external_search → review_llm (재판정)
  ├─ 근거 부족 / 불확실 → mark_needs_review
  ├─ 근거 충분 + 위험 있음 → generate_alternative (revise)
  └─ 근거 충분 + 위험 없음 → mark_pass
모든 분기 → validate_result → END
```

- 금기어 hit만으로 위반을 확정하지 않고 문맥을 함께 판단합니다. 모델이 금기어 지적을 빠뜨리면 보정합니다.
- 근거 문서에 없는 인용·근거는 검증 단계에서 제거하고, 남은 지적과 상태가 맞지 않으면 `needs_review`로 낮춥니다.
- `needs_review` 경로에서는 수정안을 만들지 않습니다. `pass`는 게시 승인이나 법률 판단이 아닙니다.

## 테스트와 코드 품질

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

자동 테스트는 실제 LLM·Tavily·BE를 호출하지 않습니다. DB 통합 테스트는 `RAG_TEST_DATABASE_URL`에
`_test`로 끝나는 전용 DB를 지정해야 실행됩니다([RAG 가이드](rag-mcp/README.md) 8장).

최근 확인 결과 (2026-10-23):

- pytest 297개 통과 (전용 test DB 포함. DB 없이 실행하면 289개 통과·8개 건너뜀), Ruff lint 통과
- 검색 품질 평가 (bge-m3): 전체 hit@1 0.81·MRR 0.87, 사회 hit@1 1.00, 기업 hit@1 0.63, 기업 격리 위반 0건
- Docker Compose: 4개 서비스 healthy, BE와 같은 UUID로 CSV 업로드 → 첨부 문서 검색 정상
- 실제 모델: 탱크데이 문구 `revise`(근거 `CASE-HIST-001`·수정안), 평범한 문구 `pass`

## 남은 일

| 담당 | 내용 |
|---|---|
| 파트 1 (Agent·판정) | 숫자 말장난(예: 518원) 등 글자만 바뀐 수정안 차단, 수정안 적용본 재검사, 지적 누락·중복 처리, `needs_review`에서 참고 수정안 제공 여부 결정 |
| 파트 2 (데이터·검색·MCP) | 시작 직후 bge-m3 첫 로드 지연 해소(시작 시 미리 로드), 평가 문항 확충, Supabase 실제 연결 확인 |
| 공통·BE | 금기어 RDB 소유·조회 방식, `campaign_purpose`·`scheduled_at` 전달 여부, FE의 7개 컬럼 CSV 안내 |

참고: [LangGraph StateGraph](https://reference.langchain.com/python/langgraph/graph/state/StateGraph),
[pgvector](https://github.com/pgvector/pgvector), [bge-m3](https://huggingface.co/BAAI/bge-m3).
