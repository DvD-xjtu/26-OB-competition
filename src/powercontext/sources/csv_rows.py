# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0.
"""Stable row-level sources for offline CSV documents."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class CSVDocumentInput(BaseModel):
    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def _validate_document(document_id: str, primary_key: str) -> None:
    if not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be nonempty and have no surrounding whitespace")  # noqa: TRY003
    if not primary_key or not primary_key.strip():
        raise ValueError("primary_key must be nonempty")  # noqa: TRY003


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    if not document_id or document_id != document_id.strip():
        raise ValueError("invalid document_id")  # noqa: TRY003
    if not primary_key_value or not primary_key_value.strip():
        raise ValueError("invalid primary key value")  # noqa: TRY003
    result = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(result) > 256:
        raise ValueError("CSV row source ID exceeds 256 characters")  # noqa: TRY003
    return result


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    _validate_document(value.document_id, value.primary_key)
    try:
        text = value.content.decode("utf-8-sig", errors="strict")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if not header or any(not column.strip() for column in header) or len(set(header)) != len(header):
            raise ValueError("CSV header must contain unique nonblank column names")  # noqa: TRY003
        if value.primary_key not in header:
            raise ValueError("primary key is not present in the header")  # noqa: TRY003
        key_index = header.index(value.primary_key)
        seen: set[str] = set()
        rows: list[CSVRowInput] = []
        for row in reader:
            if not row:
                continue
            if len(row) != len(header):
                raise ValueError("CSV record width does not match the header")  # noqa: TRY003
            key = row[key_index]
            if not key.strip() or key in seen:
                raise ValueError("primary key values must be nonblank and unique")  # noqa: TRY003
            csv_row_source_id(value.document_id, key)
            seen.add(key)
            rows.append(
                CSVRowInput(
                    document_id=value.document_id,
                    primary_key=value.primary_key,
                    primary_key_value=key,
                    columns=tuple(header),
                    values=tuple(row),
                )
            )
        return tuple(rows)
    except (csv.Error, UnicodeError) as error:
        raise ValueError("invalid CSV document") from error  # noqa: TRY003


class CSVRowAdapter:
    name = "csv-row"
    input_class = CSVRowInput
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        _validate_document(value.document_id, value.primary_key)
        if (
            not value.columns
            or len(value.columns) != len(value.values)
            or any(not column.strip() for column in value.columns)
            or len(set(value.columns)) != len(value.columns)
            or value.primary_key not in value.columns
            or value.values[value.columns.index(value.primary_key)] != value.primary_key_value
        ):
            raise ValueError("invalid CSV row")  # noqa: TRY003
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id, source_id=source_id, materialization=SourceMaterialization.CAPTURED, **value.model_dump()
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type="csv-row",
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    CSVRowAdapter(), version="1", projections=(CSVRowTextEvidenceProjection(),)
)
