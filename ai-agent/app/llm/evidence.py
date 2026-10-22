"""One evidence shape for the judge, whichever service produced it."""

from app.clients.business_mcp_client import RecentIssue
from app.schemas.review import Evidence


def to_evidence(item: Evidence | RecentIssue) -> Evidence:
    """RAG evidence already is an Evidence; an external search hit is mapped onto one.

    The URL goes into `section` so the source can still be traced from the response.
    """
    if isinstance(item, Evidence):
        return item
    return Evidence(
        document=item.title.strip() or item.source,
        section=f"{item.source} · {item.url}",
        snippet=item.snippet.strip() or item.title,
    )
