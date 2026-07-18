from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

QUALITY_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(QUALITY_ROOT))

import fixture_tool  # noqa: E402


def test_checked_in_fixture_is_reproducible() -> None:
    assert fixture_tool.validate() == []


def test_source_boundaries_are_present() -> None:
    rows = fixture_tool.joined_sales()

    assert len(rows) == 14
    assert len({row.order_id for row in rows}) == 13
    assert sum(row.discount_rate is None for row in rows) == 4
    assert sum(row.product_key is None for row in rows) == 1
    assert sum(row.product_name == "(Unmatched product)" for row in rows) == 2
    assert sum(row.region_name == "(Unmatched region)" for row in rows) == 1
    assert {row.is_returned for row in rows} == {False, True}


def test_golden_kpis_use_exact_decimal_arithmetic() -> None:
    kpi = fixture_tool.golden_results()["kpi_all"]

    assert kpi["gross_amount"] == "2838.74"
    assert kpi["cost_amount"] == "1557.75"
    assert kpi["margin_amount"] == "1280.99"
    assert Decimal(kpi["gross_amount"]) - Decimal(kpi["cost_amount"]) == Decimal(
        kpi["margin_amount"]
    )


def test_filter_scope_results_are_pinned_by_row_id() -> None:
    filters = fixture_tool.golden_results()["filter_scenarios"]

    assert filters["global_date_january"]["sales_ids"] == [1, 2, 3, 4, 5, 6, 7]
    assert filters["global_date_january_and_page_region_north"]["sales_ids"] == [1, 2, 6, 7]
    assert filters["global_date_january_and_page_region_north_and_component_category_hardware"][
        "sales_ids"
    ] == [1, 2]
    assert filters["date_intersection_global_january_and_component_from_2026_01_05"][
        "sales_ids"
    ] == [2, 3, 4, 5, 6, 7]


def test_sort_and_top_n_have_a_stable_tie_breaker() -> None:
    top = fixture_tool.golden_results()["top_2_products_by_gross_desc"]

    assert [item["product_key"] for item in top] == ["P100", "P200"]
    assert [item["gross_amount"] for item in top] == ["1110.00", "1053.50"]


def test_rls_and_workspace_negative_results_are_explicit() -> None:
    permissions = fixture_tool.golden_results()["permission_scenarios"]

    assert permissions["restricted_viewer"]["sales_ids"] == [1, 2, 6, 7, 12, 13, 14]
    assert permissions["restricted_viewer_forged_south_filter"]["row_count"] == 0
    assert permissions["foreign_administrator"] == {
        "decision": "deny",
        "error_code": "workspace_access_denied",
        "query_executed": False,
    }


def test_manifest_pins_every_data_file() -> None:
    manifest = json.loads((fixture_tool.FIXTURE_ROOT / "manifest.json").read_text())

    assert manifest["fixture_version"] == fixture_tool.FIXTURE_VERSION
    assert set(manifest["files"]) == {
        "chart_cases.json",
        "datetime_cases.json",
        "dim_product.csv",
        "dim_region.csv",
        "fact_sales.csv",
        "golden_results.json",
        "principals.json",
        "schema.json",
    }


def test_v2_fact_input_contains_canonical_utc_timestamps() -> None:
    schema = json.loads((fixture_tool.FIXTURE_ROOT / "schema.json").read_text())
    occurred_at = schema["sources"]["fact_sales"]["fields"]["occurred_at"]
    assert fixture_tool.FIXTURE_VERSION == "m3-star-v2"
    assert fixture_tool.FIXTURE_ROOT.name == "v2"
    assert occurred_at == {"nullable": False, "timezone": "UTC", "type": "datetime"}

    with (fixture_tool.FIXTURE_ROOT / "fact_sales.csv").open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 14
    assert all(row["occurred_at"].endswith("Z") for row in rows)
    parsed = [datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00")) for row in rows]
    assert all(value.tzinfo is UTC for value in parsed)
    assert parsed == sorted(parsed)


def test_datetime_golden_pins_workspace_and_dst_boundaries() -> None:
    golden = fixture_tool.golden_results()["datetime_scenarios"]

    assert golden["canonical_utc_serialization"] == {
        "input": "2026-01-05T16:30:45+08:00",
        "expected": "2026-01-05T08:30:45Z",
    }
    assert golden["hong_kong_workspace_day"] == {
        "duration_seconds": 86400,
        "end_utc": "2026-01-05T16:00:00Z",
        "local_date": "2026-01-05",
        "start_utc": "2026-01-04T16:00:00Z",
        "timezone": "Asia/Hong_Kong",
    }
    assert golden["new_york_dst_spring_forward_day"] == {
        "duration_seconds": 82800,
        "end_utc": "2026-03-09T04:00:00Z",
        "local_date": "2026-03-08",
        "start_utc": "2026-03-08T05:00:00Z",
        "timezone": "America/New_York",
    }
    assert golden["verification"] == {
        "r2_dual_database_execution_required": True,
        "scope": "generator_expected_boundaries_only",
    }


def test_every_m3_core_chart_has_a_golden_data_pointer() -> None:
    expected = {
        "kpi",
        "detail_table",
        "ranking_table",
        "bar",
        "horizontal_bar",
        "stacked_bar",
        "line",
        "area",
        "pie",
        "donut",
    }

    cases = fixture_tool.CHART_CASES["cases"]
    assert {case["component_type"] for case in cases} == expected
    assert all(case["golden_pointer"].startswith("/") for case in cases)


def test_scaled_benchmark_rows_are_deterministic_and_keep_duplicate_pairs() -> None:
    rows = fixture_tool.scaled_sales(29)

    assert rows[0]["sales_id"] == "1"
    assert rows[-1]["sales_id"] == "29"
    assert rows[12]["order_id"] == rows[13]["order_id"] == "B000001-O-DUP"
    assert rows[26]["order_id"] == rows[27]["order_id"] == "B000002-O-DUP"
    assert rows[28]["order_id"] == "B000003-O-001"
