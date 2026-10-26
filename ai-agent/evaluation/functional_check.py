"""STEP 04 인수조건(TC-01 ~ TC-08) 기능 테스트. 실제 API를 거쳐 실행한다.

    PYTHONPATH=ai-agent python ai-agent/evaluation/functional_check.py --csv functional.csv
    (실제 검색 서버까지 쓰려면 --rag-url http://localhost:8001 을 추가)

TC-01/02/05/06/07은 실제 모델을 쓴다(OPENAI_API_KEY 필요). TC-03/04/08은 실패 케이스라
실패를 직접 주입한다(근거 없음, 느린 모델, 예외 나는 노드, 검색 실패, 잘못된 수정안).
--offline은 실제 모델 대신 작은 규칙 기반 대역으로 이 스크립트 자체를 점검한다.
이때 출력은 테스트 결과가 아니다.
"""

import argparse
import asyncio
import csv
import datetime
import json
import re
import time
from types import SimpleNamespace
from unittest.mock import patch

import app.api.routes.review as review_route
import app.graph.graph as graph_module
import httpx
from app.clients.rag_mcp_client import RetrievalEvidence, RetrievalResult
from app.core.config import get_settings
from app.llm.client import set_review_model
from app.llm.openai_model import create_openai_model
from app.main import app

HIST = RetrievalEvidence(
    document="스타벅스 2026년 5월 행사명·문구 논란",
    section="보도에서 확인한 사실",
    snippet=(
        "2026년 5월 18일 스타벅스의 텀블러 행사에 탱크데이 및 책상에 탁!이라는 표현이 사용돼 "
        "비판이 제기됐다. 5월 18일이라는 행사 날짜와 표현의 결합, 박종철 사건을 연상시킨다는 "
        "지적이 핵심이다."
    ),
    rule_id="CASE-HIST-001",
    version="v1",
)
GENERAL = RetrievalEvidence(
    document="사회·역사 기준 v1",
    section="역사적 사건",
    snippet="역사적 사건·희생을 상업적 소재로 소비하는 표현은 피한다.",
    rule_id="SOC-001",
    version="v1",
)


REAL_RAG = None  # --rag-url로 설정: fixture 대신 실행 중인 RAG-MCP를 쓴다


def rag(evidence):
    """--rag-url을 주면 실제 검색, 아니면 `evidence`를 돌려주는 fixture."""
    return REAL_RAG if REAL_RAG is not None else FakeRag(evidence)


class FakeRag:
    """RAG-MCP 서버를 대신해, 케이스마다 돌려줄 근거를 정할 수 있게 한다."""

    def __init__(self, evidence=None, fail: bool = False) -> None:
        self.evidence, self.fail = evidence or [], fail

    async def search_social_context(self, query: str) -> RetrievalResult:
        if self.fail:
            raise ConnectionError("rag down")
        status = "ok" if self.evidence else "empty"
        return RetrievalResult(evidence=self.evidence, mock=False, message="", status=status)

    async def search_corporate_value(self, query, company_id, document_ids=None):
        return RetrievalResult(evidence=[], mock=False, message="", status="empty")


class OfflineModel:
    """--offline에서만 이 스크립트를 돌려 보려고 쓰는 규칙 기반 대역."""

    def generate(self, system: str, user: str) -> str:
        ad = re.search(r"<ad_text>\n(.*?)\n</ad_text>", user, re.S).group(1)
        if "카피 보조자" in system:
            count = len(re.findall(r'"index": (\d+)', user))
            return json.dumps(
                {
                    "suggestions": [
                        {"index": i, "suggestion": f"감사 이벤트 {i}"} for i in range(count)
                    ]
                },
                ensure_ascii=False,
            )
        quotes = [q for q in ("탱크데이", "안 사면 평생 후회") if q in ad]
        finding = lambda q: {  # noqa: E731
            "category": "historical_context",
            "severity": "high",
            "quote": q,
            "reason": "연상 가능",
            "evidence_ids": ["S1"],
            "criteria_ids": ["K1"],
            "needs_human_review": False,
        }
        return json.dumps(
            {
                "risk": "yes" if quotes else "no",
                "evidence_sufficient": True,
                "summary": "점검 결과",
                "findings": [finding(q) for q in quotes],
            },
            ensure_ascii=False,
        )


class Scripted:
    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)

    def generate(self, system: str, user: str) -> str:
        return self.answers.pop(0)


class SlowModel:
    def generate(self, system: str, user: str) -> str:
        time.sleep(1.5)
        return "{}"


async def review(
    text: str, rag: FakeRag, model, *, timeout: float | None = None, break_node: bool = False
) -> httpx.Response:
    set_review_model(model)
    graph = None
    try:
        if break_node:

            def boom(state):
                raise RuntimeError("injected failure")

            with patch.object(graph_module, "rule_filter", boom):
                graph = graph_module.build_graph(rag_tools=rag)
        else:
            graph = graph_module.build_graph(rag_tools=rag)
        app.state.review_graph = graph
        settings = get_settings()
        patched = SimpleNamespace(review_timeout_seconds=timeout or settings.review_timeout_seconds)
        transport = httpx.ASGITransport(app=app)
        with patch.object(review_route, "get_settings", lambda: patched):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post(
                    "/api/v1/reviews", json={"text": text, "context": {"channel": "sns"}}
                )
    finally:
        set_review_model(None)


def describe(body: dict) -> str:
    quotes = ", ".join(f"'{f['quote']}'" for f in body["findings"]) or "없음"
    return f"{body['status']} · 지적 {len(body['findings'])}건: {quotes}"


def row(tc, kind, text, expected, actual, ok, action=""):
    return [tc, kind, text, expected, actual, "통과" if ok else "실패", action]


async def run_all(model) -> list[list]:
    rows = []

    # TC-01 위험 문구 → revise + 표현·이유·근거 문서·관련 기준
    text = "5·18 기념 탱크데이 특가"
    r = await review(text, rag([HIST]), model)
    b = r.json()
    f = b["findings"][0] if b.get("findings") else {}
    ok = (
        r.status_code == 200
        and b["status"] == "revise"
        and bool(f)
        and bool(f["reason"])
        and bool(f["evidence"])
        and bool(b["related_criteria"])
    )
    rows.append(
        row(
            "TC-01",
            "정상",
            text,
            "status가 revise, 위험 표현·이유·근거 문서·관련 검수 기준이 함께 표시",
            describe(b)
            + (
                f" · 이유 있음 · 근거 문서 {f['evidence'][0]['document']} · 관련 기준 "
                f"{len(b['related_criteria'])}개"
                if f
                else ""
            ),
            ok,
        )
    )

    # TC-02 위험 없음 → pass, 지적 0건, 최종 확인 안내
    text = "가을 신메뉴 출시! 따뜻한 라떼 한 잔 어떠세요?"
    r = await review(text, rag([GENERAL]), model)
    b = r.json()
    ok = (
        r.status_code == 200
        and b["status"] == "pass"
        and b["findings"] == []
        and "확인" in b["summary"]
    )
    rows.append(
        row(
            "TC-02",
            "정상",
            text,
            "status가 pass, 지적 없음, 최종 확인이 필요하다는 안내",
            describe(b) + f" · 안내: {b['summary']}",
            ok,
        )
    )

    # TC-03 근거 없음 → needs_review + 사유
    text = "5월 18일 기념 탱크데이 특별 할인"
    r = await review(text, FakeRag([]), model)
    b = r.json()
    ok = (
        r.status_code == 200
        and b["status"] == "needs_review"
        and b["status"] != "pass"
        and bool(b["summary"])
    )
    rows.append(
        row(
            "TC-03",
            "예외·오류",
            text + " (검색된 근거 0건)",
            "pass가 아닌 needs_review가 사유와 함께 반환",
            describe(b) + f" · 사유: {b['summary']}",
            ok,
        )
    )

    # TC-04 시간 초과 / 내부 오류 / 검색 오류
    t = "5월 18일 기념 탱크데이 특별 할인"
    slow = await review(t, FakeRag([HIST]), SlowModel(), timeout=0.2)
    crash = await review(t, FakeRag([HIST]), model, break_node=True)
    search = await review(t, FakeRag(fail=True), model)
    sb = search.json()
    d_slow, d_crash = slow.json().get("detail", {}), crash.json().get("detail", {})
    has_trace = "있음" if d_slow.get("trace_id") and d_crash.get("trace_id") else "없음"
    ok = (
        slow.status_code == 504
        and d_slow.get("code") == "review_timeout"
        and d_slow.get("trace_id")
        and crash.status_code == 500
        and d_crash.get("code") == "review_failed"
        and d_crash.get("trace_id")
        and search.status_code == 200
        and sb["status"] == "needs_review"
        and sb["findings"] == []
    )
    rows.append(
        row(
            "TC-04",
            "예외·오류",
            "검수 시간 초과 · 내부 오류 · 검색 서비스 오류를 각각 발생시킴",
            "초과 504(review_timeout), 내부 오류 500(review_failed)이 trace_id와 함께, "
            "검색 오류는 임의 판단 없이 needs_review",
            f"시간 초과 {slow.status_code}({d_slow.get('code')}), 내부 오류 {crash.status_code}"
            f"({d_crash.get('code')}), trace_id {has_trace}, "
            f"검색 오류 {search.status_code} {sb.get('status')} "
            f"(지적 {len(sb.get('findings', []))}건)",
            bool(ok),
        )
    )

    # TC-05 수정안: 지적마다 수정안, 원래 표현·금기어 미포함
    text5 = "5월 18일 탱크데이, 안 사면 평생 후회"
    r = await review(text5, rag([HIST]), model)
    b5 = r.json()
    fs = b5.get("findings", [])
    ok = (
        r.status_code == 200
        and b5["status"] == "revise"
        and bool(fs)
        and all(
            x["suggestion"]
            and x["quote"] not in x["suggestion"]
            and "안 사면 평생 후회" not in x["suggestion"]
            for x in fs
        )
    )
    rows.append(
        row(
            "TC-05",
            "정상",
            text5,
            "status가 revise, 지적마다 수정안이 있고 원래 위험 표현과 금기어가 수정안에 없음",
            describe(b5) + " · 수정안: " + ", ".join(f"'{x['suggestion']}'" for x in fs),
            ok,
        )
    )

    # TC-06 수정안 반영 문구 재검수 → pass, 이전 지적 없음
    fixed = text5
    for x in sorted(fs, key=lambda x: -len(x["quote"])):
        fixed = fixed.replace(x["quote"], x["suggestion"] or "")
    r = await review(fixed, rag([HIST]), model)
    b = r.json()
    ok = r.status_code == 200 and b["status"] == "pass" and b["findings"] == []
    rows.append(
        row(
            "TC-06",
            "정상",
            fixed + " (TC-05 수정안을 반영한 문구)",
            "위험 표현이 없으면 status가 pass이고 이전 지적 사항이 표시되지 않음",
            describe(b),
            ok,
        )
    )

    # TC-07 수정 후에도 위험 표현이 남음 → revise + 표현·근거·수정안
    text = "5월 18일 기념 탱크데이, 가격을 낮췄습니다"
    r = await review(text, rag([HIST]), model)
    b = r.json()
    f = b["findings"][0] if b.get("findings") else {}
    ok = (
        r.status_code == 200
        and b["status"] == "revise"
        and bool(f)
        and bool(f["evidence"])
        and bool(f["suggestion"])
    )
    rows.append(
        row(
            "TC-07",
            "정상",
            text + " (수정했지만 위험 표현이 남은 문구)",
            "status가 revise, 남은 표현·근거·수정안이 다시 표시",
            describe(b)
            + (f" · 근거 {len(f['evidence'])}건 · 수정안 '{f['suggestion']}'" if f else ""),
            ok,
        )
    )

    # TC-08 수정안이 원래 표현을 포함 → revise 대신 needs_review + 사람 검토 표시
    judged = json.dumps(
        {
            "risk": "yes",
            "evidence_sufficient": True,
            "summary": "수정 필요",
            "findings": [
                {
                    "category": "historical_context",
                    "severity": "high",
                    "quote": "탱크데이",
                    "reason": "연상 가능",
                    "evidence_ids": ["S1"],
                    "criteria_ids": ["K1"],
                    "needs_human_review": False,
                }
            ],
        },
        ensure_ascii=False,
    )
    bad = json.dumps(
        {"suggestions": [{"index": 0, "suggestion": "탱크데이 특별 가격"}]}, ensure_ascii=False
    )
    r = await review("5월 18일 기념 탱크데이 특별 할인", FakeRag([HIST]), Scripted(judged, bad))
    b = r.json()
    ok = (
        r.status_code == 200
        and b["status"] == "needs_review"
        and bool(b["findings"])
        and all(x["needs_human_review"] for x in b["findings"])
    )
    rows.append(
        row(
            "TC-08",
            "예외·오류",
            "5월 18일 기념 탱크데이 특별 할인 (모델이 원래 표현을 포함한 수정안을 반환하도록 모사)",
            "revise 대신 needs_review, 지적 사항에 사람 검토 필요 표시",
            describe(b)
            + f" · 사람 검토 표시 {sum(x['needs_human_review'] for x in b['findings'])}건",
            ok,
        )
    )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--rag-url", default="", help="실행 중인 RAG-MCP 주소 (예: http://localhost:8001)"
    )
    args = parser.parse_args()
    settings = get_settings()
    model = OfflineModel() if args.offline else create_openai_model(settings)
    if model is None:
        print("OPENAI_API_KEY가 없어 실행할 수 없습니다. (--offline은 스크립트 점검용)")
        return 1
    global REAL_RAG
    if args.rag_url:
        from app.clients.rag_mcp_client import RagMCPTransportClient

        REAL_RAG = RagMCPTransportClient(
            args.rag_url.rstrip("/") + "/mcp", settings.http_timeout_seconds
        )
    rows = asyncio.run(run_all(model))
    for r in rows:
        print(f"{r[0]} {r[5]}  {r[4]}")
    passed = sum(r[5] == "통과" for r in rows)
    print(
        f"\n통과 {passed}/{len(rows)}"
        + ("  (--offline: 점검용, 결과 아님)" if args.offline else "")
    )
    if args.csv:
        name = "offline-standin" if args.offline else settings.openai_model
        if args.rag_url:
            name += " + 실제 RAG-MCP 검색"
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as handle:
            w = csv.writer(handle)
            w.writerow(["모델", name, "실행일", datetime.date.today().isoformat()])
            w.writerow([])
            w.writerow(["검증 ID", "유형", "입력", "기대 결과", "실제 결과", "판정", "조치"])
            w.writerows(rows)
        print(f"CSV 저장: {args.csv}")
    return 0 if passed == len(rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
