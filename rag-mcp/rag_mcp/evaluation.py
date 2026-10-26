"""전용 *_eval / *_test DB에서 실제 임베딩으로 하는 검색 평가.

회수 대상은 tests/fixtures/retrieval_cases.json에서 온다. 점수는 사실일 확률이 아니라
코사인 유사도이며, 이 보고서는 순위만 재고 검수 판정은 재지 않는다.
"""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from rag_mcp.config import ROOT, Settings
from rag_mcp.documents import (
    corporate_document,
    parse_policies,
    sample_identity,
    social_documents,
)
from rag_mcp.retrieval.embeddings import Embeddings, LocalEmbeddings
from rag_mcp.retrieval.vector_store import PgVectorStore
from rag_mcp.schemas import RetrievedEvidence

DATA = ROOT / "rag-mcp" / "data"
CASES = ROOT / "rag-mcp" / "tests" / "fixtures" / "retrieval_cases.json"
SAFE_SUFFIXES = ("_eval", "_test")


def first_hit_rank(rule_ids: list[str], expected: list[str]) -> int | None:
    """rule_id가 기대 대상인 첫 조각의 순위(1부터)."""
    return next((i for i, rule_id in enumerate(rule_ids, 1) if rule_id in expected), None)


def score_case(case: dict, evidence: list[RetrievedEvidence], latency_ms: float) -> dict:
    rule_ids = [e.rule_id for e in evidence]
    leaked = sorted(
        {e.rule_id for e in evidence if e.rule_id in case["must_not_return_rule_ids"]}
        | {
            e.rule_id
            for e in evidence
            if case["corpus"] == "corporate_demo" and e.company_id != case["company_id"]
        }
    )
    rank = first_hit_rank(rule_ids, case["expected_any_rule_ids"])
    return {
        "id": case["id"],
        "kind": case.get("kind", "retrieval" if case["expected_any_rule_ids"] else "isolation"),
        "corpus": case["corpus"],
        "query": case["query"],
        "expected": case["expected_any_rule_ids"],
        "returned": rule_ids,
        "scores": [round(e.score, 4) for e in evidence],
        "hit_rank": rank,
        "hit_score": round(evidence[rank - 1].score, 4) if rank else None,
        "top_score": round(evidence[0].score, 4) if evidence else None,
        "isolation_violations": leaked,
        "latency_ms": round(latency_ms, 1),
    }


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def summarize(results: list[dict], top_k: int) -> dict:
    def recall(rows: list[dict], k: int) -> float | None:
        return round(sum(1 for r in rows if r["hit_rank"] and r["hit_rank"] <= k) / len(rows), 4)

    def block(rows: list[dict]) -> dict:
        return {
            "cases": len(rows),
            **{f"hit@{k}": recall(rows, k) for k in (1, 3, top_k)},
            "mrr": round(sum(1 / r["hit_rank"] for r in rows if r["hit_rank"]) / len(rows), 4),
            "misses": [r["id"] for r in rows if not r["hit_rank"]],
        }

    retrieval = [r for r in results if r["kind"] == "retrieval"]
    negatives = [r for r in results if r["kind"] == "negative"]
    latencies = sorted(r["latency_ms"] for r in results)
    hit_scores = [r["hit_score"] for r in retrieval if r["hit_score"] is not None]
    negative_scores = [r["top_score"] for r in negatives if r["top_score"] is not None]
    return {
        "top_k": top_k,
        "retrieval": {
            "all": block(retrieval),
            **{
                corpus: block([r for r in retrieval if r["corpus"] == corpus])
                for corpus in sorted({r["corpus"] for r in retrieval})
            },
        },
        "isolation_violations": {
            r["id"]: r["isolation_violations"] for r in results if r["isolation_violations"]
        },
        "isolation_cases_returning_results": [
            r["id"] for r in results if r["kind"] == "isolation" and r["returned"]
        ],
        "scores": {
            "hit_score_min": min(hit_scores, default=None),
            "hit_score_mean": _mean(hit_scores),
            "negative_top_score_max": max(negative_scores, default=None),
            "negative_top_score_mean": _mean(negative_scores),
            "negative_cases": len(negatives),
        },
        "latency_ms": {
            "p50": round(statistics.median(latencies), 1),
            "p95": round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 1),
            "max": latencies[-1],
        },
    }


async def load_corpus(store: PgVectorStore, embeddings: Embeddings, settings: Settings) -> dict:
    """전용 DB를 비우고 manifest의 사회 문서와 모든 데모 CSV를 색인한다."""
    await store.initialize()
    async with store.connection() as conn:
        await conn.execute("DELETE FROM adcheck_rag.documents")
    counts = {"social": 0, "corporate": 0}
    for document in await social_documents(DATA, embeddings):
        await store.replace(document)
        counts["social"] += 1
    for path in sorted((DATA / "corporate").glob("*/*.csv")):
        rows = parse_policies(path.name, path.read_bytes(), settings, *sample_identity(path))
        await store.replace(await corporate_document(rows, embeddings))
        counts["corporate"] += 1
    return counts


async def evaluate(
    store: PgVectorStore, cases: list[dict], *, top_k: int = 5, min_score: float = 0.0
) -> list[dict]:
    results = []
    for case in cases:
        corporate = case["corpus"] == "corporate_demo"
        started = time.perf_counter()
        evidence = await store.search(
            case["query"],
            collection="corporate" if corporate else "social",
            company_id=case["company_id"] if corporate else None,
            top_k=top_k,
            min_score=min_score,
        )
        results.append(score_case(case, evidence, (time.perf_counter() - started) * 1000))
    return results


async def run(args: argparse.Namespace) -> dict:
    from psycopg.conninfo import conninfo_to_dict

    if not conninfo_to_dict(args.database_url)["dbname"].endswith(SAFE_SUFFIXES):
        raise SystemExit("평가는 이름이 _eval 또는 _test로 끝나는 전용 DB에서만 실행합니다.")
    settings = Settings(rag_database_url=args.database_url)
    embeddings = LocalEmbeddings(settings)
    store = PgVectorStore(settings, embeddings)
    fixture = json.loads(args.cases.read_text("utf-8"))
    indexed = await load_corpus(store, embeddings, settings)
    await embeddings.embed(["warm-up"])  # 응답 시간에서 모델 로드 시간을 뺀다
    results = await evaluate(store, fixture["cases"], top_k=args.top_k, min_score=args.min_score)
    return {
        "embedding_profile": embeddings.profile,
        "chunking": {"tokens": settings.rag_chunk_tokens, "overlap": settings.rag_chunk_overlap},
        "min_score": args.min_score,
        "fixture_version": fixture["version"],
        "indexed_documents": indexed,
        "summary": summarize(results, args.top_k),
        "cases": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AdCheck RAG retrieval evaluation")
    parser.add_argument("--database-url", required=True, help="Dedicated *_eval or *_test DB")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--output", type=Path, help="Write the full JSON report here")
    args = parser.parse_args()
    report = asyncio.run(run(args))
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
