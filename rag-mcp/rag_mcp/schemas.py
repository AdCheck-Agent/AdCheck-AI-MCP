from pydantic import BaseModel, ConfigDict, Field


class SearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=2000)


class CorporateQuery(SearchQuery):
    company_id: str = Field(min_length=1, max_length=100)


class RetrievedEvidence(BaseModel):
    document: str
    section: str
    snippet: str
    rule_id: str
    version: str


class SearchResult(BaseModel):
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    mock: bool = True
    message: str = "[MOCK] 검색 미구현: 실제 근거 문서를 반환하지 않습니다."
