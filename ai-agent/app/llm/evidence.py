"""어느 서비스가 만들었든 판정에는 근거를 한 가지 형태로 넘긴다."""

from app.clients.business_mcp_client import RecentIssue
from app.schemas.review import Evidence


def to_evidence(item: Evidence | RecentIssue) -> Evidence:
    """RAG 근거는 이미 Evidence다. 외부 검색 결과는 Evidence로 바꾼다.

    URL은 `section`에 넣어 응답에서도 출처를 추적할 수 있게 한다.
    """
    if isinstance(item, Evidence):
        return item
    return Evidence(
        document=item.title.strip() or item.source,
        section=f"{item.source} · {item.url}",
        snippet=item.snippet.strip() or item.title,
    )
