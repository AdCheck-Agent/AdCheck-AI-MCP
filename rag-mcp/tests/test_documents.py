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
        assert len(rows) == 3 and all(r.synthetic for r in rows)


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
        [rows[0] | {"synthetic": "maybe"}],
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
    assert all(d.company_id is None and not d.synthetic for d in docs)
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
