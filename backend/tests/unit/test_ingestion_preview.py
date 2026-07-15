from datetime import date, datetime
from pathlib import Path

import pytest
from bi_system.ingestion.domain import FileKind
from bi_system.ingestion.preview import SourcePreviewError, preview_source_file
from openpyxl import Workbook


def test_csv_preview_profiles_columns_and_stops_at_limit(tmp_path: Path) -> None:
    csv_path = tmp_path / "metrics.csv"
    csv_path.write_text(
        "城市,数量,占比,启用,日期\n"
        "北京,10,1.5,true,2026-07-15\n"
        "上海,,2.0,false,2026-07-16\n"
        "广州,30,3.5,true,2026-07-17\n",
        encoding="utf-8-sig",
    )

    preview = preview_source_file(csv_path, file_kind=FileKind.CSV, max_rows=2)

    assert preview.truncated is True
    assert [column.source_name for column in preview.columns] == [
        "城市",
        "数量",
        "占比",
        "启用",
        "日期",
    ]
    assert [column.inferred_type for column in preview.columns] == [
        "string",
        "integer",
        "decimal",
        "boolean",
        "date",
    ]
    assert preview.columns[1].null_count == 1
    assert len(preview.rows) == 2
    assert preview.rows[0]["column_1"] == "北京"


def test_xlsx_preview_serializes_dates_and_preserves_formula_text(tmp_path: Path) -> None:
    workbook_path = tmp_path / "metrics.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = "数据"
    worksheet.append(["日期", "公式"])
    worksheet.append([date(2026, 7, 15), "=1+1"])
    workbook.save(workbook_path)
    workbook.close()

    preview = preview_source_file(
        workbook_path,
        file_kind=FileKind.XLSX,
        max_rows=10,
        sheet_name="数据",
    )

    assert preview.sheet_names == ("数据",)
    assert preview.selected_sheet == "数据"
    assert preview.columns[0].inferred_type == "datetime"
    assert preview.rows[0]["column_1"] == datetime(2026, 7, 15).isoformat()
    assert preview.rows[0]["column_2"] == "=1+1"


def test_preview_rejects_empty_source(tmp_path: Path) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")

    with pytest.raises(SourcePreviewError, match="header row"):
        preview_source_file(csv_path, file_kind=FileKind.CSV, max_rows=10)


def test_csv_preview_rejects_worksheet_option(tmp_path: Path) -> None:
    csv_path = tmp_path / "metrics.csv"
    csv_path.write_text("name,value\nfoo,1\n", encoding="utf-8")

    with pytest.raises(SourcePreviewError, match="do not contain worksheets"):
        preview_source_file(
            csv_path,
            file_kind=FileKind.CSV,
            max_rows=10,
            sheet_name="Sheet1",
        )
