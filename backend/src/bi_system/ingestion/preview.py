import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from itertools import islice
from pathlib import Path

from bi_system.ingestion.domain import FileKind
from bi_system.ingestion.readers import iter_csv_rows, iter_xlsx_rows, xlsx_sheet_names

JsonCell = str | int | float | bool | None
INTEGER_PATTERN = re.compile(r"^[+-]?(?:0|[1-9]\d*)$")
DECIMAL_PATTERN = re.compile(r"^[+-]?(?:0|[1-9]\d*)\.\d+$")


class SourcePreviewError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PreviewColumn:
    key: str
    source_name: str
    inferred_type: str
    null_count: int


@dataclass(frozen=True, slots=True)
class SourcePreview:
    sheet_names: tuple[str, ...]
    selected_sheet: str | None
    columns: tuple[PreviewColumn, ...]
    rows: tuple[dict[str, JsonCell], ...]
    truncated: bool


def preview_source_file(
    path: Path,
    *,
    file_kind: FileKind,
    max_rows: int,
    encoding: str = "utf-8-sig",
    sheet_name: str | None = None,
) -> SourcePreview:
    if max_rows <= 0:
        raise ValueError("max_rows must be positive")

    try:
        if file_kind is FileKind.CSV:
            if sheet_name is not None:
                raise SourcePreviewError("CSV files do not contain worksheets")
            return _build_preview(
                iter_csv_rows(path, encoding=encoding),
                max_rows=max_rows,
                sheet_names=(),
                selected_sheet=None,
            )

        sheets = xlsx_sheet_names(path)
        selected_sheet = sheet_name or (sheets[0] if sheets else None)
        if selected_sheet is None:
            raise SourcePreviewError("XLSX workbook does not contain a worksheet")
        return _build_preview(
            iter_xlsx_rows(path, sheet_name=selected_sheet),
            max_rows=max_rows,
            sheet_names=sheets,
            selected_sheet=selected_sheet,
        )
    except UnicodeDecodeError as exc:
        raise SourcePreviewError(
            "CSV encoding does not match the selected encoding",
        ) from exc


def _build_preview(
    rows: Iterator[tuple[object, ...]],
    *,
    max_rows: int,
    sheet_names: tuple[str, ...],
    selected_sheet: str | None,
) -> SourcePreview:
    sampled_rows = list(islice(rows, max_rows + 2))
    if not sampled_rows:
        raise SourcePreviewError("Source file does not contain a header row")

    header = sampled_rows[0]
    data_rows = sampled_rows[1 : max_rows + 1]
    truncated = len(sampled_rows) > max_rows + 1
    width = max([len(header), *(len(row) for row in data_rows)], default=0)
    if width == 0:
        raise SourcePreviewError("Source file header is empty")

    keys = tuple(f"column_{index + 1}" for index in range(width))
    source_names = tuple(
        _source_column_name(header[index] if index < len(header) else None, index)
        for index in range(width)
    )
    columns = tuple(
        PreviewColumn(
            key=keys[index],
            source_name=source_names[index],
            inferred_type=_infer_column_type(
                [row[index] if index < len(row) else None for row in data_rows],
            ),
            null_count=sum(
                _is_blank(row[index] if index < len(row) else None) for row in data_rows
            ),
        )
        for index in range(width)
    )
    normalized_rows = tuple(
        {
            keys[index]: _json_cell(row[index] if index < len(row) else None)
            for index in range(width)
        }
        for row in data_rows
    )

    return SourcePreview(
        sheet_names=sheet_names,
        selected_sheet=selected_sheet,
        columns=columns,
        rows=normalized_rows,
        truncated=truncated,
    )


def _source_column_name(value: object, index: int) -> str:
    if value is None or not str(value).strip():
        return f"Column {index + 1}"
    return str(value).strip()


def _infer_column_type(values: list[object]) -> str:
    kinds = {_value_kind(value) for value in values if not _is_blank(value)}
    if not kinds:
        return "string"
    if kinds <= {"integer"}:
        return "integer"
    if kinds <= {"integer", "decimal"}:
        return "decimal"
    if kinds <= {"boolean"}:
        return "boolean"
    if kinds <= {"date"}:
        return "date"
    if kinds <= {"date", "datetime"}:
        return "datetime"
    return "string"


def _value_kind(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, (float, Decimal)):
        return "decimal"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if not isinstance(value, str):
        return "string"

    normalized = value.strip()
    if normalized.lower() in {"true", "false", "yes", "no"}:
        return "boolean"
    if INTEGER_PATTERN.fullmatch(normalized):
        return "integer"
    if DECIMAL_PATTERN.fullmatch(normalized):
        try:
            Decimal(normalized)
        except InvalidOperation:
            return "string"
        return "decimal"
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        pass
    else:
        return "datetime" if "T" in normalized or " " in normalized else "date"
    return "string"


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _json_cell(value: object) -> JsonCell:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int, float)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)
