"""Build and validate the deterministic M3 dashboard acceptance fixture."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

FIXTURE_VERSION = "m3-star-v2"
FIXTURE_ROOT = Path(__file__).parent / "fixture" / "v2"

PRODUCT_FIELDS = (
    "product_key",
    "product_name",
    "category",
    "launch_date",
    "is_active",
)
REGION_FIELDS = (
    "region_key",
    "region_name",
    "region_group",
    "is_restricted",
)
SALES_FIELDS = (
    "sales_id",
    "order_id",
    "sold_on",
    "occurred_at",
    "product_key",
    "region_key",
    "quantity",
    "gross_amount",
    "cost_amount",
    "is_returned",
    "discount_rate",
)

PRODUCTS: tuple[dict[str, str], ...] = (
    {
        "product_key": "P100",
        "product_name": "Widget Alpha",
        "category": "Hardware",
        "launch_date": "2025-01-15",
        "is_active": "true",
    },
    {
        "product_key": "P200",
        "product_name": "Widget Beta",
        "category": "Hardware",
        "launch_date": "2025-06-01",
        "is_active": "true",
    },
    {
        "product_key": "P300",
        "product_name": "Service Plan",
        "category": "Services",
        "launch_date": "2024-11-20",
        "is_active": "false",
    },
    {
        # Repeated display labels must not be treated as dimension keys.
        "product_key": "P400",
        "product_name": "Widget Alpha",
        "category": "Accessories",
        "launch_date": "2026-02-01",
        "is_active": "true",
    },
)

REGIONS: tuple[dict[str, str], ...] = (
    {
        "region_key": "R-NORTH",
        "region_name": "North",
        "region_group": "Domestic",
        "is_restricted": "false",
    },
    {
        "region_key": "R-SOUTH",
        "region_name": "South",
        "region_group": "Domestic",
        "is_restricted": "false",
    },
    {
        "region_key": "R-SECRET",
        "region_name": "Strategic",
        "region_group": "Restricted",
        "is_restricted": "true",
    },
)

SALES: tuple[dict[str, str], ...] = (
    {
        "sales_id": "1",
        "order_id": "O-001",
        "sold_on": "2026-01-03",
        "occurred_at": "2026-01-02T16:30:00Z",
        "product_key": "P100",
        "region_key": "R-NORTH",
        "quantity": "2",
        "gross_amount": "200.00",
        "cost_amount": "120.00",
        "is_returned": "false",
        "discount_rate": "0.10",
    },
    {
        "sales_id": "2",
        "order_id": "O-002",
        "sold_on": "2026-01-05",
        "occurred_at": "2026-01-04T16:00:00Z",
        "product_key": "P200",
        "region_key": "R-NORTH",
        "quantity": "1",
        "gross_amount": "150.50",
        "cost_amount": "90.25",
        "is_returned": "false",
        "discount_rate": "",
    },
    {
        "sales_id": "3",
        "order_id": "O-003",
        "sold_on": "2026-01-05",
        "occurred_at": "2026-01-04T16:30:00Z",
        "product_key": "P300",
        "region_key": "R-SOUTH",
        "quantity": "3",
        "gross_amount": "300.00",
        "cost_amount": "120.00",
        "is_returned": "false",
        "discount_rate": "0.05",
    },
    {
        "sales_id": "4",
        "order_id": "O-004",
        "sold_on": "2026-01-10",
        "occurred_at": "2026-01-10T04:00:00Z",
        "product_key": "P100",
        "region_key": "R-SOUTH",
        "quantity": "1",
        "gross_amount": "100.00",
        "cost_amount": "60.00",
        "is_returned": "true",
        "discount_rate": "0.00",
    },
    {
        "sales_id": "5",
        "order_id": "O-005",
        "sold_on": "2026-01-12",
        "occurred_at": "2026-01-12T01:00:00Z",
        "product_key": "P200",
        "region_key": "R-SECRET",
        "quantity": "4",
        "gross_amount": "602.00",
        "cost_amount": "361.00",
        "is_returned": "false",
        "discount_rate": "0.10",
    },
    {
        "sales_id": "6",
        "order_id": "O-006",
        "sold_on": "2026-01-20",
        "occurred_at": "2026-01-20T08:00:00Z",
        "product_key": "P300",
        "region_key": "R-NORTH",
        "quantity": "1",
        "gross_amount": "99.99",
        "cost_amount": "40.00",
        "is_returned": "false",
        "discount_rate": "",
    },
    {
        "sales_id": "7",
        "order_id": "O-007",
        "sold_on": "2026-01-31",
        "occurred_at": "2026-01-31T15:59:59Z",
        "product_key": "P999",
        "region_key": "R-NORTH",
        "quantity": "2",
        "gross_amount": "80.00",
        "cost_amount": "20.00",
        "is_returned": "false",
        "discount_rate": "0.20",
    },
    {
        "sales_id": "8",
        "order_id": "O-008",
        "sold_on": "2026-02-01",
        "occurred_at": "2026-01-31T16:00:00Z",
        "product_key": "P100",
        "region_key": "R-SOUTH",
        "quantity": "5",
        "gross_amount": "500.00",
        "cost_amount": "300.00",
        "is_returned": "false",
        "discount_rate": "0.05",
    },
    {
        "sales_id": "9",
        "order_id": "O-009",
        "sold_on": "2026-02-07",
        "occurred_at": "2026-02-07T02:00:00Z",
        "product_key": "P200",
        "region_key": "R-SOUTH",
        "quantity": "2",
        "gross_amount": "301.00",
        "cost_amount": "180.50",
        "is_returned": "false",
        "discount_rate": "",
    },
    {
        "sales_id": "10",
        "order_id": "O-010",
        "sold_on": "2026-02-14",
        "occurred_at": "2026-02-14T06:00:00Z",
        "product_key": "P300",
        "region_key": "R-SECRET",
        "quantity": "1",
        "gross_amount": "120.00",
        "cost_amount": "50.00",
        "is_returned": "true",
        "discount_rate": "0.00",
    },
    {
        "sales_id": "11",
        "order_id": "O-011",
        "sold_on": "2026-02-20",
        "occurred_at": "2026-02-20T10:00:00Z",
        "product_key": "P100",
        "region_key": "R999",
        "quantity": "1",
        "gross_amount": "110.00",
        "cost_amount": "66.00",
        "is_returned": "false",
        "discount_rate": "",
    },
    {
        "sales_id": "12",
        "order_id": "O-012",
        "sold_on": "2026-02-28",
        "occurred_at": "2026-02-28T01:00:00Z",
        "product_key": "",
        "region_key": "R-NORTH",
        "quantity": "1",
        "gross_amount": "75.25",
        "cost_amount": "30.00",
        "is_returned": "false",
        "discount_rate": "0.15",
    },
    {
        "sales_id": "13",
        "order_id": "O-DUP",
        "sold_on": "2026-02-28",
        "occurred_at": "2026-02-28T02:00:00Z",
        "product_key": "P100",
        "region_key": "R-NORTH",
        "quantity": "1",
        "gross_amount": "100.00",
        "cost_amount": "60.00",
        "is_returned": "false",
        "discount_rate": "0.00",
    },
    {
        "sales_id": "14",
        "order_id": "O-DUP",
        "sold_on": "2026-02-28",
        "occurred_at": "2026-02-28T03:00:00Z",
        "product_key": "P100",
        "region_key": "R-NORTH",
        "quantity": "1",
        "gross_amount": "100.00",
        "cost_amount": "60.00",
        "is_returned": "false",
        "discount_rate": "0.00",
    },
)

DATETIME_CASES: dict[str, Any] = {
    "fixture_version": FIXTURE_VERSION,
    "timestamp_field": {
        "source": "fact_sales",
        "field": "occurred_at",
        "input_format": "ISO 8601 UTC with trailing Z",
    },
    "canonicalization_cases": [
        {
            "case_id": "canonical_utc_serialization",
            "input": "2026-01-05T16:30:45+08:00",
        }
    ],
    "workspace_day_cases": [
        {
            "case_id": "hong_kong_workspace_day",
            "timezone": "Asia/Hong_Kong",
            "local_date": "2026-01-05",
        },
        {
            "case_id": "new_york_dst_spring_forward_day",
            "timezone": "America/New_York",
            "local_date": "2026-03-08",
        },
    ],
    "verification": {
        "scope": "generator_expected_boundaries_only",
        "r2_dual_database_execution_required": True,
    },
}

PRINCIPALS: dict[str, Any] = {
    "fixture_version": FIXTURE_VERSION,
    "workspace_id": "11111111-1111-1111-1111-111111111111",
    "foreign_workspace_id": "22222222-2222-2222-2222-222222222222",
    "principals": [
        {
            "key": "administrator",
            "workspace_id": "11111111-1111-1111-1111-111111111111",
            "permissions": ["dashboards:manage", "datasets:manage", "datasets:query"],
            "rls_region_keys": None,
            "expected_access": "allow_all_rows",
        },
        {
            "key": "editor",
            "workspace_id": "11111111-1111-1111-1111-111111111111",
            "permissions": ["dashboards:manage", "datasets:query"],
            "rls_region_keys": None,
            "expected_access": "allow_all_rows_but_deny_dataset_administration",
        },
        {
            "key": "restricted_viewer",
            "workspace_id": "11111111-1111-1111-1111-111111111111",
            "permissions": ["datasets:query"],
            "rls_region_keys": ["R-NORTH"],
            "expected_access": "allow_north_rows_only_and_deny_dashboard_edit",
        },
        {
            "key": "foreign_administrator",
            "workspace_id": "22222222-2222-2222-2222-222222222222",
            "permissions": ["dashboards:manage", "datasets:manage", "datasets:query"],
            "rls_region_keys": None,
            "expected_access": "deny_cross_workspace_before_query_compilation",
        },
    ],
}

SCHEMA: dict[str, Any] = {
    "fixture_version": FIXTURE_VERSION,
    "join_type": "left",
    "sources": {
        "fact_sales": {
            "file": "fact_sales.csv",
            "primary_key": ["sales_id"],
            "business_key": ["order_id"],
            "fields": {
                "sales_id": {"type": "integer", "nullable": False},
                "order_id": {"type": "string", "nullable": False},
                "sold_on": {"type": "date", "nullable": False},
                "occurred_at": {"type": "datetime", "timezone": "UTC", "nullable": False},
                "product_key": {"type": "string", "nullable": True},
                "region_key": {"type": "string", "nullable": False},
                "quantity": {"type": "integer", "nullable": False},
                "gross_amount": {"type": "decimal", "precision": 12, "scale": 2, "nullable": False},
                "cost_amount": {"type": "decimal", "precision": 12, "scale": 2, "nullable": False},
                "is_returned": {"type": "boolean", "nullable": False},
                "discount_rate": {"type": "decimal", "precision": 5, "scale": 2, "nullable": True},
            },
        },
        "dim_product": {
            "file": "dim_product.csv",
            "primary_key": ["product_key"],
            "fields": {
                "product_key": {"type": "string", "nullable": False},
                "product_name": {"type": "string", "nullable": False},
                "category": {"type": "string", "nullable": False},
                "launch_date": {"type": "date", "nullable": False},
                "is_active": {"type": "boolean", "nullable": False},
            },
        },
        "dim_region": {
            "file": "dim_region.csv",
            "primary_key": ["region_key"],
            "fields": {
                "region_key": {"type": "string", "nullable": False},
                "region_name": {"type": "string", "nullable": False},
                "region_group": {"type": "string", "nullable": False},
                "is_restricted": {"type": "boolean", "nullable": False},
            },
        },
    },
    "relationships": [
        {
            "from": "fact_sales.product_key",
            "to": "dim_product.product_key",
            "cardinality": "many_to_one",
        },
        {
            "from": "fact_sales.region_key",
            "to": "dim_region.region_key",
            "cardinality": "many_to_one",
        },
    ],
}

CHART_CASES: dict[str, Any] = {
    "fixture_version": FIXTURE_VERSION,
    "cases": [
        {
            "case_id": "kpi-gross",
            "component_type": "kpi",
            "golden_pointer": "/kpi_all/gross_amount",
        },
        {
            "case_id": "detail-products",
            "component_type": "detail_table",
            "golden_pointer": "/table_by_product",
        },
        {
            "case_id": "ranking-products-top2",
            "component_type": "ranking_table",
            "golden_pointer": "/top_2_products_by_gross_desc",
        },
        {
            "case_id": "bar-category",
            "component_type": "bar",
            "golden_pointer": "/bar_and_pie_by_category",
        },
        {
            "case_id": "horizontal-bar-region",
            "component_type": "horizontal_bar",
            "golden_pointer": "/bar_by_region",
        },
        {
            "case_id": "stacked-category-region",
            "component_type": "stacked_bar",
            "golden_pointer": "/stacked_bar_category_by_region",
        },
        {
            "case_id": "line-month",
            "component_type": "line",
            "golden_pointer": "/line_and_area_by_month",
        },
        {
            "case_id": "area-month",
            "component_type": "area",
            "golden_pointer": "/line_and_area_by_month",
        },
        {
            "case_id": "pie-category",
            "component_type": "pie",
            "golden_pointer": "/bar_and_pie_by_category",
        },
        {
            "case_id": "donut-category",
            "component_type": "donut",
            "golden_pointer": "/bar_and_pie_by_category",
        },
    ],
    "filter_cases": [
        {
            "case_id": "filter-global-date",
            "golden_pointer": "/filter_scenarios/global_date_january",
        },
        {
            "case_id": "filter-page-region",
            "golden_pointer": "/filter_scenarios/global_date_january_and_page_region_north",
        },
        {
            "case_id": "filter-component-category",
            "golden_pointer": (
                "/filter_scenarios/global_date_january_and_page_region_north_"
                "and_component_category_hardware"
            ),
        },
        {
            "case_id": "filter-date-intersection",
            "golden_pointer": (
                "/filter_scenarios/date_intersection_global_january_and_component_from_2026_01_05"
            ),
        },
    ],
}


@dataclass(frozen=True)
class JoinedSale:
    sales_id: int
    order_id: str
    sold_on: date
    occurred_at: datetime
    product_key: str | None
    product_name: str
    category: str
    region_key: str
    region_name: str
    quantity: int
    gross_amount: Decimal
    cost_amount: Decimal
    is_returned: bool
    discount_rate: Decimal | None


def _unique_index(rows: Sequence[Mapping[str, str]], key: str) -> dict[str, Mapping[str, str]]:
    index: dict[str, Mapping[str, str]] = {}
    for row in rows:
        value = row[key]
        if value in index:
            raise ValueError(f"duplicate dimension key: {key}={value}")
        index[value] = row
    return index


def joined_sales() -> tuple[JoinedSale, ...]:
    products = _unique_index(PRODUCTS, "product_key")
    regions = _unique_index(REGIONS, "region_key")
    result: list[JoinedSale] = []
    for raw in SALES:
        product_key = raw["product_key"] or None
        product = products.get(product_key or "")
        region = regions.get(raw["region_key"])
        result.append(
            JoinedSale(
                sales_id=int(raw["sales_id"]),
                order_id=raw["order_id"],
                sold_on=date.fromisoformat(raw["sold_on"]),
                occurred_at=_parse_timestamp(raw["occurred_at"]),
                product_key=product_key,
                product_name=(product or {}).get("product_name", "(Unmatched product)"),
                category=(product or {}).get("category", "(Unmatched product)"),
                region_key=raw["region_key"],
                region_name=(region or {}).get("region_name", "(Unmatched region)"),
                quantity=int(raw["quantity"]),
                gross_amount=Decimal(raw["gross_amount"]),
                cost_amount=Decimal(raw["cost_amount"]),
                is_returned=raw["is_returned"] == "true",
                discount_rate=Decimal(raw["discount_rate"]) if raw["discount_rate"] else None,
            )
        )
    return tuple(result)


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include an explicit UTC offset")
    return parsed.astimezone(UTC)


def _canonical_utc(value: str | datetime) -> str:
    parsed = _parse_timestamp(value) if isinstance(value, str) else value.astimezone(UTC)
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _workspace_day_expectation(case: Mapping[str, str]) -> dict[str, Any]:
    timezone_name = case["timezone"]
    local_date = date.fromisoformat(case["local_date"])
    zone = ZoneInfo(timezone_name)
    local_start = datetime.combine(local_date, time.min, tzinfo=zone)
    local_end = local_start + timedelta(days=1)
    start_utc = local_start.astimezone(UTC)
    end_utc = local_end.astimezone(UTC)
    return {
        "timezone": timezone_name,
        "local_date": local_date.isoformat(),
        "start_utc": _canonical_utc(start_utc),
        "end_utc": _canonical_utc(end_utc),
        "duration_seconds": int((end_utc - start_utc).total_seconds()),
    }


def datetime_expectations() -> dict[str, Any]:
    result = {
        case["case_id"]: {
            "input": case["input"],
            "expected": _canonical_utc(case["input"]),
        }
        for case in DATETIME_CASES["canonicalization_cases"]
    }
    result.update(
        {
            case["case_id"]: _workspace_day_expectation(case)
            for case in DATETIME_CASES["workspace_day_cases"]
        }
    )
    result["verification"] = DATETIME_CASES["verification"]
    return result


def _aggregate(rows: Iterable[JoinedSale]) -> dict[str, Any]:
    materialized = tuple(rows)
    gross = sum((row.gross_amount for row in materialized), Decimal(0))
    cost = sum((row.cost_amount for row in materialized), Decimal(0))
    return {
        "sales_ids": [row.sales_id for row in materialized],
        "row_count": len(materialized),
        "distinct_order_count": len({row.order_id for row in materialized}),
        "quantity": sum(row.quantity for row in materialized),
        "gross_amount": _money(gross),
        "cost_amount": _money(cost),
        "margin_amount": _money(gross - cost),
        "returned_row_count": sum(row.is_returned for row in materialized),
    }


def _group(rows: Sequence[JoinedSale], *attributes: str) -> list[dict[str, Any]]:
    buckets: dict[tuple[Any, ...], list[JoinedSale]] = defaultdict(list)
    for row in rows:
        buckets[tuple(getattr(row, attribute) for attribute in attributes)].append(row)
    result: list[dict[str, Any]] = []
    for key, bucket in buckets.items():
        labels = {attribute: value for attribute, value in zip(attributes, key, strict=True)}
        result.append({**labels, **_aggregate(bucket)})
    return sorted(result, key=lambda item: tuple(str(item[attribute]) for attribute in attributes))


def _month(row: JoinedSale) -> str:
    return row.sold_on.strftime("%Y-%m")


def golden_results() -> dict[str, Any]:
    rows = joined_sales()
    january = tuple(row for row in rows if date(2026, 1, 1) <= row.sold_on < date(2026, 2, 1))
    january_north = tuple(row for row in january if row.region_key == "R-NORTH")
    january_north_hardware = tuple(row for row in january_north if row.category == "Hardware")
    viewer_rows = tuple(row for row in rows if row.region_key == "R-NORTH")

    monthly_buckets: dict[str, list[JoinedSale]] = defaultdict(list)
    for row in rows:
        monthly_buckets[_month(row)].append(row)
    monthly = [
        {"month": month, **_aggregate(bucket)} for month, bucket in sorted(monthly_buckets.items())
    ]

    by_product = _group(rows, "product_key", "product_name")
    top_products = sorted(
        by_product,
        key=lambda item: (-Decimal(item["gross_amount"]), str(item["product_key"])),
    )[:2]

    return {
        "fixture_version": FIXTURE_VERSION,
        "join_semantics": (
            "fact LEFT JOIN dimensions; unknown and NULL keys use explicit unmatched labels"
        ),
        "decimal_semantics": "base-10 exact arithmetic; money rounded to scale 2 only for output",
        "date_semantics": "ISO date; ranges are [start, end) in fixture timezone Asia/Hong_Kong",
        "datetime_semantics": (
            "inputs and outputs are canonical UTC ISO 8601; workspace days resolve in an explicit "
            "IANA timezone to UTC [start, end) boundaries"
        ),
        "datetime_scenarios": datetime_expectations(),
        "kpi_all": {
            **_aggregate(rows),
            "null_discount_row_count": sum(row.discount_rate is None for row in rows),
            "null_product_key_row_count": sum(row.product_key is None for row in rows),
            "unknown_product_key_row_count": sum(
                row.product_name == "(Unmatched product)" and row.product_key is not None
                for row in rows
            ),
            "unknown_region_key_row_count": sum(
                row.region_name == "(Unmatched region)" for row in rows
            ),
        },
        "table_by_product": by_product,
        "bar_and_pie_by_category": _group(rows, "category"),
        "bar_by_region": _group(rows, "region_name"),
        "stacked_bar_category_by_region": _group(rows, "category", "region_name"),
        "line_and_area_by_month": monthly,
        "top_2_products_by_gross_desc": top_products,
        "filter_scenarios": {
            "global_date_january": _aggregate(january),
            "global_date_january_and_page_region_north": _aggregate(january_north),
            "global_date_january_and_page_region_north_and_component_category_hardware": _aggregate(
                january_north_hardware
            ),
            "date_intersection_global_january_and_component_from_2026_01_05": _aggregate(
                row for row in january if row.sold_on >= date(2026, 1, 5)
            ),
        },
        "permission_scenarios": {
            "administrator": {"decision": "allow", **_aggregate(rows)},
            "editor": {"decision": "allow", **_aggregate(rows)},
            "restricted_viewer": {"decision": "allow_after_rls", **_aggregate(viewer_rows)},
            "restricted_viewer_forged_south_filter": {
                "decision": "allow_empty_after_rls_and_user_filter_intersection",
                **_aggregate(row for row in viewer_rows if row.region_key == "R-SOUTH"),
            },
            "foreign_administrator": {
                "decision": "deny",
                "error_code": "workspace_access_denied",
                "query_executed": False,
            },
        },
    }


def _csv_bytes(fields: Sequence[str], rows: Sequence[Mapping[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def rendered_files() -> dict[str, bytes]:
    files = {
        "chart_cases.json": _json_bytes(CHART_CASES),
        "datetime_cases.json": _json_bytes(DATETIME_CASES),
        "dim_product.csv": _csv_bytes(PRODUCT_FIELDS, PRODUCTS),
        "dim_region.csv": _csv_bytes(REGION_FIELDS, REGIONS),
        "fact_sales.csv": _csv_bytes(SALES_FIELDS, SALES),
        "golden_results.json": _json_bytes(golden_results()),
        "principals.json": _json_bytes(PRINCIPALS),
        "schema.json": _json_bytes(SCHEMA),
    }
    manifest = {
        "fixture_version": FIXTURE_VERSION,
        "generator": "spikes/m3/quality/fixture_tool.py",
        "files": {
            name: {
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
            for name, content in sorted(files.items())
        },
    }
    files["manifest.json"] = _json_bytes(manifest)
    return files


def generate(root: Path = FIXTURE_ROOT) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in rendered_files().items():
        (root / name).write_bytes(content)


def scaled_sales(row_count: int) -> tuple[dict[str, str], ...]:
    """Repeat the base fact rows deterministically for performance runs."""
    if row_count <= 0:
        raise ValueError("row_count must be positive")
    result: list[dict[str, str]] = []
    for offset in range(row_count):
        cycle = offset // len(SALES) + 1
        source = SALES[offset % len(SALES)]
        row = dict(source)
        row["sales_id"] = str(offset + 1)
        row["order_id"] = f"B{cycle:06d}-{source['order_id']}"
        result.append(row)
    return tuple(result)


def generate_benchmark(root: Path, row_count: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    data_files = {
        "dim_product.csv": _csv_bytes(PRODUCT_FIELDS, PRODUCTS),
        "dim_region.csv": _csv_bytes(REGION_FIELDS, REGIONS),
        "fact_sales.csv": _csv_bytes(SALES_FIELDS, scaled_sales(row_count)),
        "schema.json": _json_bytes(SCHEMA),
    }
    manifest = {
        "fixture_version": FIXTURE_VERSION,
        "profile": "deterministic_performance_scale",
        "fact_row_count": row_count,
        "files": {
            name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            for name, content in sorted(data_files.items())
        },
    }
    data_files["benchmark_manifest.json"] = _json_bytes(manifest)
    for name, content in data_files.items():
        (root / name).write_bytes(content)


def validate(root: Path = FIXTURE_ROOT) -> list[str]:
    errors: list[str] = []
    expected = rendered_files()
    for name, content in expected.items():
        path = root / name
        if not path.exists():
            errors.append(f"missing: {path}")
        elif path.read_bytes() != content:
            errors.append(f"content mismatch: {path}")
    extras = sorted(
        path.name for path in root.glob("*") if path.is_file() and path.name not in expected
    )
    errors.extend(f"unexpected file: {root / name}" for name in extras)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "benchmark", "check", "summary"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rows", type=int, default=100_000)
    args = parser.parse_args()
    if args.action == "generate":
        output = args.output or FIXTURE_ROOT
        generate(output)
        print(f"generated {FIXTURE_VERSION} in {output}")
        return 0
    if args.action == "benchmark":
        output = args.output or Path(".tmp") / f"m3-star-benchmark-{args.rows}"
        generate_benchmark(output, args.rows)
        print(f"generated {FIXTURE_VERSION} benchmark ({args.rows} rows) in {output}")
        return 0
    if args.action == "check":
        output = args.output or FIXTURE_ROOT
        errors = validate(output)
        if errors:
            print("\n".join(errors))
            return 1
        print(f"validated {FIXTURE_VERSION}: {len(rendered_files())} files")
        return 0
    print(json.dumps(golden_results()["kpi_all"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
