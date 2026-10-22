from pydantic import BaseModel, ConfigDict, Field


class SearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=2000)


class RecentIssue(BaseModel):
    title: str
    url: str
    snippet: str


class SearchResult(BaseModel):
    results: list[RecentIssue] = Field(default_factory=list)
    mock: bool = True
    message: str = "[MOCK] 외부검색은 보류된 기능입니다. 실제 검색을 수행하지 않았습니다."
