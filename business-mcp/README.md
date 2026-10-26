# Business MCP 외부검색

Business 서비스는 두 MCP Tool을 제공합니다.

| Tool | 역할 |
|---|---|
| `search_recent_issue` | Tavily Search API로 공개 사실 검색 (HTTP API도 함께 제공) |
| `save_checkpoint` | 검수 단계 완료와 최종 결과를 BE에 저장 (`PATCH /api/v1/reviews/checkpoint`) |

MCP SDK v1.30.0의 Streamable HTTP를 사용하며 두 경로는 같은 검색 함수를 호출합니다.
Agent는 `BusinessMCPTransportClient`로 MCP Tool을 호출합니다. 기존 HTTP adapter(`BusinessMCPClient`)는 진단용으로 남겨 두었습니다.

## 적용한 제한

| 항목 | 동작 |
|---|---|
| Agent 검수 요청당 검색 | 최대 1회, 요청별 graph state에 기록 |
| 검색 조건 | 근거 부족 + 판정 노드가 명시한 검색어 존재 + 미시도 |
| 검색 결과 수 | 최대 3개, 설정으로 줄일 수 있음 |
| 검색 시간 | Business의 전체 Tavily 요청 최대 5초, Agent의 전체 Tool 대기도 최대 5초 |
| 재시도·리다이렉트 | 하지 않음 |
| Extract·자동 답변 | 호출하지 않음 |
| 결과 없음 | 정상 빈 배열을 전달하고 최종 판정 노드가 전체 근거 재평가 |
| 실패·timeout | MCP `isError`와 구조화된 실패 상태를 전달. HTTP는 기존 502/503/504 유지 |
| 결과 있음 | 판정 노드가 다시 평가, 결과 존재만으로 통과하지 않음 |

판정 노드(`review_llm`)는 근거가 부족하고 외부검색으로 확인할 수 있는 공개 사실일 때만 검색어를 만들고,
검색어에서 개인정보를 지운 뒤 `external_search_query`로 넘깁니다. 근거가 충분하면 Tavily를 호출하지 않습니다.
광고 의도 불명확이나 내부 정책 부족은 검색어 없이 보류합니다.

## 설정과 로컬 실행

저장소 루트에서 기존 venv를 활성화합니다. `mcp`는 루트 requirements에 포함되어 있습니다.

```bash
source .venv/bin/activate
cp -n .env.example .env
```

`.env`를 편집해 아래 값을 설정합니다. 실제 key는 Git에 포함하지 않습니다.

```dotenv
TAVILY_API_KEY=발급받은_API_KEY
TAVILY_TIMEOUT_SECONDS=5
TAVILY_MAX_RESULTS=3
```

timeout은 0 초과 5 이하, 결과 수는 1~3만 허용합니다.
API key 없이도 서버와 health는 실행되며, 검색은 네트워크 호출 없이 `unavailable`을 반환합니다.

```bash
python -m uvicorn business_mcp.server:app --app-dir business-mcp --host 0.0.0.0 --port 8002
```

동일 포트의 Docker 서비스가 실행 중이면 로컬 실행 전에 중지하거나 다른 포트를 사용합니다.
Compose로 실행할 때는 저장소 루트에서:

```bash
docker compose up --build -d business-mcp ai-agent
```

Compose는 key와 검색 제한을 Business 컨테이너에 전달합니다. 설정 변경 후 컨테이너를 재생성합니다.

## MCP Tool 계약

- 로컬 endpoint: `http://localhost:8002/mcp`
- Compose 내부 endpoint: `http://business-mcp:8002/mcp`
- Tool 이름: `search_recent_issue`
- 입력: `{"query": "확인할 공개 사실"}` — 앞뒤 공백 제거 후 1~400자
- `tools/list`에 입력·출력 JSON schema를 공개합니다.
- 반환: `structuredContent`에 아래 SearchResult 전체를 담고, `content`에도 동일 JSON을 제공합니다.
- `ok`, `empty`는 `isError: false`, `timeout`, `unavailable`, `error`는 `isError: true`입니다.
  실패여도 `structuredContent`의 상태·메시지는 보존합니다.
- 잘못된 입력은 검색 전에 MCP Tool 오류로 반환하며, 이때 SearchResult는 없을 수 있습니다.
- 허용 호스트는 localhost, 127.0.0.1, Compose의 business-mcp와 테스트 호스트입니다.
  다른 도메인으로 배포할 때는 서버의 허용 호스트를 명시적으로 조정해야 합니다.

실행 중인 서버에 MCP SDK로 연결하는 예시입니다. 실제 Tool 호출은 Tavily 검색을 수행합니다.

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def search(query: str):
    async with streamable_http_client("http://localhost:8002/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            response = await session.call_tool("search_recent_issue", {"query": query})
            # 실패 상태도 structuredContent에 담길 수 있으므로 함께 확인합니다.
            return response
```

MCP 세션과 Agent의 ReviewState는 별개입니다. 서버는 결과를 반환하며,
Agent의 client·검색 노드가 이를 검증해 `external_search_result`에 저장합니다.
`related_criteria`는 Business에서 항상 `[]`입니다. 관련 검수 기준 태그는 Agent 판정 단계가 만듭니다.

## HTTP Tool 계약

```http
POST /tools/search_recent_issue
Content-Type: application/json
```

Request — 앞뒤 공백 제거 후 1~400자 검색어 하나만 받습니다.

```json
{"query":"확인할 기업이나 사건의 최근 후속 보도"}
```

Response의 합성 예시:

```json
{
  "status": "ok",
  "mock": false,
  "related_criteria": [],
  "results": [
    {
      "title": "검색 결과 제목",
      "url": "https://example.com/article",
      "snippet": "검색 API가 반환한 내용",
      "source": "example.com",
      "score": 0.8,
      "published_at": null,
      "retrieved_at": "2026-10-22T06:00:00Z",
      "content_check": "not_checked"
    }
  ],
  "message": "검색 결과입니다. 원문 별도 확인 및 사실 검증은 수행하지 않았습니다."
}
```

| status | 의미 |
|---|---|
| `ok` | 사용할 수 있는 검색 결과가 있음 |
| `empty` | 검색은 성공했지만 사용할 결과가 없음 |
| `unavailable` | key 또는 Agent의 client가 설정되지 않음 |
| `timeout` | 제한 시간 초과 |
| `error` | 공급자 HTTP 오류, 네트워크 또는 응답 형식 오류 |

정상 검색은 HTTP 200이며, 결과가 없어도 `status: empty`, `results: []`로 정상 반환합니다.
실패는 HTTP 502 (`error`), key 미설정은 HTTP 503 (`unavailable`), 시간 초과는
HTTP 504 (`timeout`)입니다. 오류 본문도 같은 SearchResult 모델을 사용합니다.
입력 검증 오류는 HTTP 422입니다.
`mock: false`는 mock 결과가 아니라는 뜻이며, 실제 요청 성공 여부는 `status`로 판단합니다.

검색 API 결과의 title·URL·content를 검증하고, 동일 URL 및 빈 title/content를 제외합니다.
게시 시각은 timezone이 있는 ISO 또는 RFC 형식만 변환하며, 누락·잘못된 값·날짜만 있는 값은
`published_at: null`입니다. `source`는 URL의 호스트명이며 언론사 신뢰도 인증이 아닙니다.
score는 관련성 점수이며 사실일 확률이 아닙니다. 기간 필터와 사건 발생일 확인은 이번 범위에 없습니다.
모든 결과는 `content_check: not_checked`로 반환합니다.

## `save_checkpoint` Tool 계약

Agent가 검수 단계를 마칠 때마다 호출해 BE에 진행 상황을 저장합니다.

- 입력: `original_text_id`(UUID, Agent 요청의 `review_id`), `checkpoint_level`, 선택 `result`·`error`
- 단계: `BANNED_WORD_CHECK`, `SOCIAL_HISTORICAL_SEARCH`, `COMPANY_VALUES_SEARCH`, `EXTERNAL_SEARCH`,
  `FINAL_ASSESSMENT`, `ALTERNATIVE_GENERATION`, `OUTPUT_VALIDATION`, `COMPLETED`, `FAILED`
- `result`(최종 `ReviewResponse`)는 `COMPLETED`에만 넣을 수 있습니다.
- `error`(`code`: `REVIEW_TIMEOUT` | `REVIEW_ERROR`, `message`, `stage`, `trace_id`)는 `FAILED`에만, `FAILED`에는 반드시 넣습니다.
- BE 호출: `PATCH {ADCHECK_BE_BASE_URL}/api/v1/reviews/checkpoint`, 헤더 `X-Internal-Key: {INTERNAL_API_KEY}`
- 반환: `CheckpointResult`(`ok | timeout | unavailable | error`, HTTP 상태, BE 오류 코드). `ok`가 아니면 `isError: true`
- Tool은 한 번만 보내고 스스로 재시도하지 않습니다. BE는 받은 단계로 덮어쓰므로, 늦게 도착한 재시도가 단계를 되돌릴 수 있기 때문입니다.
  재시도는 Agent가 맡습니다. `retryable` 실패면 **다음 단계를 보내기 전에** 한 번만 다시 보내 순서를 지킵니다.
- 내부 key는 설정에서만 읽고 Tool 인자로 받지 않습니다. 주소나 key가 없으면 네트워크 호출 없이 `unavailable`입니다.

```dotenv
ADCHECK_BE_BASE_URL=http://host.docker.internal:8080   # Compose 안에서 맥의 BE를 부를 때
INTERNAL_API_KEY=<BE와 같은 값>
CHECKPOINT_ENABLED=true                                # Agent 쪽 설정
```

Agent는 [checkpoint.py](../ai-agent/app/checkpoint.py)에서 이벤트를 큐에 쌓아 한 건씩 순서대로 보냅니다.
노드는 기다리지 않으므로 BE가 느리거나 실패해도 검수는 계속됩니다. 실패·건너뛴 단계는 보내지 않고,
실행 예외·시간 초과 시에는 `COMPLETED` 대신 `FAILED`와 `error`를 보냅니다. 끝내 저장하지 못한 단계는 로그(`checkpoint not saved`)에 남습니다.

## Agent 연결 위치

- `app/clients/business_mcp_client.py`: `BusinessMCPTransportClient`(두 Tool), 진단용 HTTP adapter
- `app/graph/nodes/retrieve_external_evidence.py`: 외부검색 Tool 호출과 Agent 측 시간 제한
- `app/graph/graph.py`: 근거 부족 시 조건부 검색, 검색 후 재판정, 재검색 방지
- `app/checkpoint.py`, `app/services/review.py`: 단계 이벤트를 `save_checkpoint`로 전달
- `app/main.py`: client 생성과 그래프 주입

외부검색 후에는 성공·빈 결과·실패·timeout 모두 판정 노드로 전달합니다. 검색 노드는 `status`를 확정하지 않고,
실패를 정상 빈 결과로 바꾸지 않습니다. 외부검색 실패는 최종 결과의 `missing_information`에 남습니다.
원문과 검색 결과는 실행 지시가 아니라 참고 데이터로만 사용합니다.

검색 1회 제한은 하나의 graph 실행에 대한 정책입니다. 별도의 review 요청을 다시 보내거나
Tool endpoint를 직접 다시 호출하면 각각 새 호출이므로 전역 rate limit은 아닙니다.

## 테스트

저장소 루트에서 실행합니다. 테스트는 fake key와 mock transport만 사용하며 Tavily를 호출하지 않습니다.

```bash
python -m pytest business-mcp/tests ai-agent/tests/test_external_search.py ai-agent/tests/test_checkpoint.py -q
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

정상 결과·빈 결과·key 없음·401/429/500·리다이렉트 차단·형식 오류·네트워크 실패·전체 timeout,
그래프에서 재검색하지 않는지와 모든 검색 상태의 최종 판정 전달,
외부검색이 비어도 기존 RAG 근거로 판단 가능한지를 검증합니다.
MCP 테스트는 SDK로 초기화·Tool 목록 조회·호출을 수행하고 입력 검증, 전체 결과 보존,
오류 상태 구분, 허용되지 않은 호스트 차단을 확인합니다. 테스트의 HTTP 연결은 ASGI transport입니다.

2026-10-22 수동 확인: MCP SDK → Business → 실제 Tavily를 중립적인 NASA 검색어로 1회 호출해
`ok`, 결과 1개와 출처 메타데이터 반환을 확인했습니다. MCP 구간은 ASGI transport를 사용했으므로
배포 환경의 포트·프록시 연결까지 검증한 것은 아닙니다.

2026-10-23 수동 확인: Compose의 Business MCP로 "518 탱크데이 탁", "5·18 탱크데이 광고 문구 문제"를 검색해
각각 3건 모두 해당 논란 보도·자료가 반환됐습니다(약 2초). 이미 보도된 사례라서 찾을 수 있는 것이며,
새 문구는 외부검색만으로 문제 여부가 나오지 않습니다. 결과에는 뉴스 외 유튜브·나무위키도 섞입니다.

Tavily 계약 참고: [공식 Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search).
