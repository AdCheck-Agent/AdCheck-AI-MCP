import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rag_mcp.config import Settings
from rag_mcp.documents import COLUMNS, corporate_document, parse_policies, social_documents
from rag_mcp.errors import DocumentError
from rag_mcp.server import create_app

DATA = Path(__file__).resolve().parents[1] / "data"
SAMPLE = DATA / "corporate/taegeon_beauty/corporate_values.csv"


def serialize(rows: list[dict]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def test_all_samples_have_equivalent_csv_xlsx() -> None:
    samples = list(DATA.glob("corporate/*/*.csv"))
    assert len(samples) == 6
    for csv_file in samples:
        xlsx = csv_file.with_suffix(".xlsx")
        rows = parse_policies(csv_file.name, csv_file.read_bytes(), Settings())
        assert rows == parse_policies(xlsx.name, xlsx.read_bytes(), Settings())
        # corporate_values adds brand-direction rows (mission, tone, audience) to the 3 rules.
        expected = 8 if csv_file.stem == "corporate_values" else 3
        assert len(rows) == expected


@pytest.mark.parametrize("extension", ["pdf", "docx", "xls", "txt"])
def test_disallowed_upload_format(extension: str) -> None:
    with pytest.raises(DocumentError) as error:
        parse_policies(f"file.{extension}", b"test", Settings())
    assert error.value.status == 415


def test_bad_headers_duplicate_rows_and_company_mismatch() -> None:
    with pytest.raises(DocumentError):
        parse_policies("x.csv", b"title,content\na,b", Settings())
    rows = [
        r.model_dump(mode="json")
        for r in parse_policies(SAMPLE.name, SAMPLE.read_bytes(), Settings())
    ]
    for invalid in (
        [rows[0], rows[0]],
        [rows[0], rows[1] | {"company_id": "other"}],
        [rows[0] | {"content": "   "}],
    ):
        with pytest.raises(DocumentError):
            parse_policies("x.csv", serialize(invalid), Settings())


def test_invalid_xlsx_and_encoding() -> None:
    for name, content in [("x.xlsx", b"broken"), ("x.csv", b"\xff\xff")]:
        with pytest.raises(DocumentError):
            parse_policies(name, content, Settings())


def test_size_and_row_limits() -> None:
    with pytest.raises(DocumentError) as error:
        parse_policies(SAMPLE.name, SAMPLE.read_bytes(), Settings(rag_max_upload_bytes=10))
    assert error.value.status == 413
    with pytest.raises(DocumentError):
        parse_policies(SAMPLE.name, SAMPLE.read_bytes(), Settings(rag_max_rows=1))


async def test_row_chunking_preserves_metadata(embeddings) -> None:
    rows = parse_policies(SAMPLE.name, SAMPLE.read_bytes(), Settings())
    rows[0].content = "가" * 260
    doc = await corporate_document(rows, embeddings)
    first = [c for c in doc.chunks if c.metadata["row_id"] == rows[0].row_id]
    assert len(first) == 3
    assert "".join(c.content for c in first) == rows[0].content
    assert all(c.section == rows[0].section for c in first)


async def test_social_manifest_excludes_corporate_and_research(embeddings) -> None:
    docs = await social_documents(DATA, embeddings)
    assert len(docs) == 12
    assert all(d.company_id is None for d in docs)
    assert all(d.metadata["source_urls"] and d.chunks for d in docs)


def test_upload_rejects_wrong_tenant_before_embedding() -> None:
    with TestClient(create_app()) as client:
        response = client.put(
            "/api/v1/companies/other/documents/wrong",
            files={"file": (SAMPLE.name, SAMPLE.read_bytes())},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDENTITY_MISMATCH"


def test_upload_pdf_rejected() -> None:
    with TestClient(create_app()) as client:
        response = client.put(
            "/api/v1/companies/demo/documents/demo", files={"file": ("policy.pdf", b"%PDF")}
        )
    assert response.status_code == 415


def test_xlsx_accepts_blank_trailing_optional_columns() -> None:
    from openpyxl import Workbook

    row = parse_policies(SAMPLE.name, SAMPLE.read_bytes(), Settings())[0].model_dump(mode="json")
    order = [c for c in COLUMNS if c not in ("source_url", "published_at")]
    order += ["source_url", "published_at"]
    wb = Workbook()
    sheet = wb.active
    sheet.title = "policies"
    sheet.append(order)
    sheet.append([row[c] for c in order[:-2]])  # Excel stores no cells for the blank tail
    buffer = io.BytesIO()
    wb.save(buffer)
    parsed = parse_policies("x.xlsx", buffer.getvalue(), Settings())
    assert parsed[0].source_url is None and parsed[0].published_at is None
    assert parsed[0].content == row["content"]


async def test_social_chunks_drop_link_targets_but_keep_sources(embeddings) -> None:
    docs = await social_documents(DATA, embeddings)
    for doc in docs:
        assert all("](" not in c.content and "http" not in c.content for c in doc.chunks)
        assert doc.metadata["source_urls"]
    history = next(d for d in docs if d.metadata["rule_id"] == "RULE-HIST-001")
    assert any("국립5·18민주묘지" in c.content for c in history.chunks)  # link label stays


@pytest.mark.parametrize("count", [0, 1, 96, 97, 110, 181, 300, 1000])
def test_token_windows_are_even_bounded_and_overlapping(count) -> None:
    from rag_mcp.retrieval.embeddings import token_windows

    windows = token_windows(count, 96, 12)
    if not count:
        assert windows == []
        return
    assert windows[0][0] == 0 and windows[-1][1] == count
    sizes = {end - start for start, end in windows}
    assert max(sizes) <= 96 and max(sizes) - min(sizes) <= 1
    assert all(windows[i][1] - windows[i + 1][0] >= 12 for i in range(len(windows) - 1))
