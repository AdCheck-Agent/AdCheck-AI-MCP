# RAG 문서 데이터 v1

작성·출처 확인일: 2026-10-22 (Asia/Seoul).

사회·역사 자료는 확인 가능한 기관 자료와 기사에 근거해 작성했습니다.
다만 아래 검수 규칙은 **프로젝트가 작성한 판단 보조 기준**이며, 정부·언론·기관의 공식 광고 심의 규칙이나 법률 판단이 아닙니다.
기업 문서는 요청한 두 기업명을 사용한 **개발용 합성 정책**입니다. 실제 기업의 공표 정책·인증·이행 실적으로 인용하면 안 됩니다.

## 구성

| 위치 | 내용 | 검색 근거 적재 |
|---|---|---|
| `social/criteria/` | 출처 기반 프로젝트 검수 기준 6개 | manifest에 등록한 문서만 |
| `social/cases/` | 확인한 보도·기관 판단 사례 6개 | manifest에 등록한 문서만 |
| `corporate/taegeon_beauty/` | 태건뷰티 CSV/XLSX 합성 문서 3종 | 명시적 업로드 후 include_synthetic=true 검색 |
| `corporate/seojun_roasters/` | 서준로스터스 CSV/XLSX 합성 문서 3종 | 명시적 업로드 후 include_synthetic=true 검색 |
| `research/` | 미확인 사례·정정 및 조사 기록 | 제외 |
| `sources.json` | 출처 ID·URL·발행일·확인 범위 | 본문으로 적재하지 않음 |
| `manifest.json` | 적재 대상과 실제/합성 성격의 명시적 목록 | 적재 작업의 입력 |
| `../tests/fixtures/retrieval_cases.json` | 합성 검색 평가 문항 | 제외 |

pgvector 적재·검색과 CSV/XLSX 업로드를 구현했습니다. 실행·컬럼·API 계약은 [RAG 가이드](../README.md)를 확인하세요.
사회 문서는 CLI로 적재하며 기업 샘플은 자동 적재하지 않습니다. Agent의 검색 노드 연결은 별도 작업입니다.

## 문서의 세 가지 성격

1. `project_guideline`: 외부 사실을 토대로 프로젝트가 작성한 검수 원칙. 원 출처의 명령문·법조항으로 표현하지 않습니다.
2. `reported_case`: 기사에서 확인한 광고·논란·대응의 짧은 요약. 광고 원본을 직접 확인한 것과 구분합니다.
3. `synthetic_company_policy`: 가상 정책. 모든 응답에 합성 근거임을 보존합니다.

`sources_checked`는 링크 자료가 기재 내용을 뒷받침함을 조사한 상태입니다.
기업의 의도, 위법성, 매출 영향, 모든 후속 조치까지 독립적으로 입증했다는 의미가 아닙니다.
기사 원문·스크린샷·PDF 전체를 복제하지 않았고, 사실은 짧게 재서술했습니다.

## 기업 식별자

| company_id | 표시 이름 | 성격 |
|---|---|---|
| `taegeon_beauty` | 태건뷰티 | 뷰티 기업을 가정한 합성 정책 |
| `seojun_roasters` | 서준로스터스 | 카페를 가정한 합성 정책 |

두 ID는 샘플용이며 Backend 기업 ID와 합의한 후 매핑합니다.
RAG 검색 API는 기업 ID를 필터로 사용합니다. Agent는 RAG_RETRIEVAL_ENABLED=true일 때 실제 MCP client로 검색합니다.

## metadata와 chunking 계약

사회 문서는 YAML front matter와 heading을 해석해 적재합니다. 기업 문서는 CSV/XLSX 11개 컬럼을 사용합니다.
기업의 새 문서 유형은 기업가치·지속가능경영보고서·윤리경영 정책이며, 이전 Markdown은 research/legacy_corporate에 보관했습니다.

- `document_id`, `rule_id`, `title`, `record_type`, `category`, `version`: 필수 식별 정보
- `company_id`: 기업 문서에만 필수. 사회 기준은 `null`
- `synthetic`: 합성 여부. 실제 근거와 혼합해 표시하지 않음
- `source_ids`: `sources.json`의 출처 ID. 합성 정책은 빈 목록
- `verification_status`, `verified_at`: 확인 수준과 확인일. 합성 정책은 사실 확인 대상이 아님
- `retrieval_enabled`: 후보 적재 여부. 실제 허용 목록은 `manifest.json`

chunk 생성 시 추가·보존할 필드:

| 필드 | 생성/보존 기준 |
|---|---|
| `chunk_id` | 사회 문서는 section 번호, 기업 문서는 row_id + 분할 번호. 기업·문서 키와 함께 식별 |
| `document` | 문서의 title |
| `section` | heading 경로 |
| `snippet` | 이 저장소 문서에 실제로 존재하는 본문 구간 |
| `rule_id`, `version`, `record_type`, `synthetic` | 문서 metadata 유지 |
| `company_id` | 기업 문서는 필수 검색 필터 |
| `source_ids`, `source_urls` | 출처 레지스트리와 연결해 보존 |
| `score` | 검색 시 생성. 원문 metadata가 아니며 사실 확률도 아님 |

기관 사실, 보도 요약, 프로젝트 기준을 하나의 무표시 chunk로 합치지 않습니다.
작은 section 단위로 나누고 필요한 문서 성격·출처를 각 chunk에 붙입니다.
본문에 회사명이 나오는 사회 사례를 그 회사의 기업 정책으로 오분류하지 않습니다.
`category`는 현재 Agent Literal 범위 안에서 사용하고 세부 주제는 section으로 표현합니다.

## 적재 전 확인

- manifest에 명시한 문서만 적재하고 data 전체를 재귀적으로 수집하지 않습니다.
- research, 평가 문항, README, 출처 레지스트리는 검색 대상에서 제외합니다.
- 합성 기업 정책은 실제 운영 근거와 분리합니다. 실제 기업 정책으로 교체하기 전 demo임을 표시합니다.
- 출처 변경·정정·삭제 시 해당 문서와 chunk version을 갱신합니다.
- 과거 광고 사례는 현재도 논란이 진행 중이라는 근거로 사용하지 않습니다.
- 사진·영상 맥락이 핵심인 사례는 text-only 검수의 한계를 함께 전달합니다.
- 이 자료는 역사·인권을 모두 망라하지 않습니다. 기준 밖 입력은 근거 충분으로 간주하지 않습니다.

기관·기사 출처는 각 문서와 [sources.json](sources.json)에 기재했습니다.
사용자가 제시한 사례 중 확인하지 못한 항목과 날짜 수정 사항은 [조사 기록](research/case_verification.md)에 남겼습니다.
