import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from rag_mcp.config import Settings
from rag_mcp.errors import DocumentError
from rag_mcp.retrieval.embeddings import Embeddings
from rag_mcp.schemas import Chunk, DocumentRecord, PolicyRow

COLUMNS = list(PolicyRow.model_fields)


def _table(filename: str, data: bytes, settings: Settings) -> list[list]:
    suffix = Path(filename).suffix.lower()
    if len(data) > settings.rag_max_upload_bytes:
        raise DocumentError("파일 크기 제한을 초과했습니다.", "FILE_TOO_LARGE", 413)
    try:
        if suffix == ".csv":
            table = []
            for row in csv.reader(io.StringIO(data.decode("utf-8-sig")), strict=True):
                if len(table) > settings.rag_max_rows:
                    raise DocumentError("행 수 제한을 초과했습니다.")
                table.append(row)
            return table
        if suffix != ".xlsx":
            raise DocumentError(
                "CSV 또는 XLSX만 지원합니다. PDF는 지원하지 않습니다.", "UNSUPPORTED_FILE_TYPE", 415
            )
        from openpyxl import load_workbook

        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(x.file_size for x in archive.infolist()) > 50 * 1024 * 1024:
                raise DocumentError("XLSX 압축 해제 크기 제한을 초과했습니다.")
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
        try:
            if wb.sheetnames != ["policies"]:
                raise DocumentError("XLSX는 policies 시트 하나만 포함해야 합니다.")
            sheet = wb["policies"]
            sheet.reset_dimensions()
            table = []
            for cells in sheet.iter_rows():
                if len(table) > settings.rag_max_rows:
                    raise DocumentError("행 수 제한을 초과했습니다.")
                if any(cell.data_type == "f" for cell in cells):
                    raise DocumentError("수식은 지원하지 않습니다. 계산된 값을 넣어 주세요.")
                table.append([cell.value for cell in cells])
            # Excel omits trailing empty cells, so blank optional last columns arrive short.
            width = len(table[0]) if table else 0
            return [row + [None] * (width - len(row)) for row in table]
        finally:
            wb.close()
    except (UnicodeError, csv.Error, zipfile.BadZipFile, KeyError, ValueError) as exc:
        if isinstance(exc, DocumentError):
            raise
        raise DocumentError(
            "파일을 읽을 수 없습니다. UTF-8 CSV 또는 정상 XLSX인지 확인하세요."
        ) from exc


def parse_policies(filename: str, data: bytes, settings: Settings) -> list[PolicyRow]:
    table = _table(filename, data, settings)
    if not table:
        raise DocumentError("헤더와 최소 한 개의 정책 행이 필요합니다.")
    header = [str(x).strip() if x is not None else "" for x in table[0]]
    if len(set(header)) != len(header) or set(header) != set(COLUMNS):
        raise DocumentError(f"컬럼을 확인하세요. 필수 헤더: {', '.join(COLUMNS)}")
    rows = []
    seen = set()
    for number, values in enumerate(table[1:], 2):
        if all(x in (None, "") for x in values):
            continue
        if len(values) != len(header):
            raise DocumentError(f"{number}행: 컬럼 수가 헤더와 다릅니다.")
        obj = dict(zip(header, values, strict=True))
        for key in ("source_url", "published_at"):
            if obj[key] in (None, ""):
                obj[key] = None
        if isinstance(obj["published_at"], datetime):
            obj["published_at"] = obj["published_at"].date()
        try:
            row = PolicyRow.model_validate(obj)
        except ValidationError as exc:
            details = "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in exc.errors())
            raise DocumentError(f"{number}행: {details}") from exc
        if row.row_id in seen:
            raise DocumentError(f"{number}행: 중복 row_id입니다.")
        seen.add(row.row_id)
        rows.append(row)
    if not rows:
        raise DocumentError("최소 한 개의 정책 행이 필요합니다.")
    identity = ("company_id", "document_id", "document_type", "title")
    if any(any(getattr(r, key) != getattr(rows[0], key) for key in identity) for r in rows):
        raise DocumentError("한 파일에는 같은 기업·문서·유형·제목만 넣으세요.")
    return rows


async def corporate_document(rows: list[PolicyRow], embeddings: Embeddings) -> DocumentRecord:
    first = rows[0]
    chunks = []
    for row in rows:
        for i, content in enumerate(await embeddings.split(row.content)):
            chunks.append(
                Chunk(
                    chunk_id=f"{row.row_id}:{i}",
                    section=row.section,
                    content=content,
                    metadata={
                        "row_id": row.row_id,
                        # File order; attached-document retrieval returns chunks in this order.
                        "ordinal": len(chunks),
                        "source_urls": [str(row.source_url)] if row.source_url else [],
                        "published_at": row.published_at.isoformat() if row.published_at else None,
                    },
                )
            )
    canonical = json.dumps([r.model_dump(mode="json") for r in rows], sort_keys=True)
    return DocumentRecord(
        company_id=first.company_id,
        document_id=first.document_id,
        corpus="corporate",
        document_type=first.document_type,
        title=first.title,
        checksum=hashlib.sha256(canonical.encode()).hexdigest(),
        chunks=chunks,
        metadata={
            "category": "corporate_value",
            "verification_status": "user_provided_not_independently_verified",
            "record_type": "uploaded_company_document",
        },
    )


async def social_documents(data_dir: Path, embeddings: Embeddings) -> list[DocumentRecord]:
    manifest = json.loads((data_dir / "manifest.json").read_text("utf-8"))
    registry = json.loads((data_dir / "sources.json").read_text("utf-8"))
    sources = {s["source_id"]: s["url"] for s in registry["sources"]}
    documents = []
    for item in manifest["documents"]:
        if item["corpus"] != "social":
            continue
        path = (data_dir / item["path"]).resolve()
        if not path.is_relative_to((data_dir / "social").resolve()):
            raise DocumentError("사회 문서 manifest 경로가 social 범위를 벗어났습니다.")
        text = path.read_text("utf-8")
        _, front, body = text.split("---", 2)
        meta = yaml.safe_load(front)
        if meta["document_id"] != item["document_id"] or not meta["retrieval_enabled"]:
            raise DocumentError("사회 문서 manifest와 metadata가 일치하지 않습니다.")
        chunks, section = [], meta["title"]
        # Each heading retains its own provenance instead of mixing facts and project guidance.
        sections = re.split(r"(?m)^#{1,6} (.+)\n", body)
        for i, part in enumerate(sections):
            if i % 2:
                section = part.strip()
                continue
            if not part.strip():
                continue
            for content in await embeddings.split(part.strip()):
                chunks.append(
                    Chunk(chunk_id=f"section:{len(chunks)}", section=section, content=content)
                )
        documents.append(
            DocumentRecord(
                company_id=None,
                document_id=meta["document_id"],
                corpus="social",
                document_type=meta["record_type"],
                title=meta["title"],
                checksum=hashlib.sha256(text.encode()).hexdigest(),
                chunks=chunks,
                metadata={
                    "rule_id": meta["rule_id"],
                    "record_type": meta["record_type"],
                    "category": meta["category"],
                    "verification_status": meta["verification_status"],
                    "source_ids": meta["source_ids"],
                    "source_urls": [sources[s] for s in meta["source_ids"]],
                },
            )
        )
    return documents
