from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from bi_system.modeling.contracts import AggregateFunction


@dataclass(frozen=True, slots=True)
class CoverageMeasure:
    field_name: str
    aggregate: AggregateFunction


@dataclass(frozen=True, slots=True)
class CaseCoverage:
    case_id: str
    component_type: str
    disposition: Literal["execute", "gap"]
    dimensions: tuple[str, ...] = ()
    measures: tuple[CoverageMeasure, ...] = ()
    series_dimension: str | None = None
    max_series: int | None = None
    time_grain: Literal["day", "week", "month", "quarter", "year"] | None = None
    top_n: int | None = None
    sort_dimension: bool = False
    expected_gap_code: str | None = None
    golden_projection: tuple[tuple[str, str], ...] = ()


GROSS_SUM = CoverageMeasure("gross_amount", AggregateFunction.SUM)

CASE_COVERAGE: tuple[CaseCoverage, ...] = (
    CaseCoverage(
        case_id="kpi-gross",
        component_type="kpi",
        disposition="execute",
        measures=(GROSS_SUM,),
        golden_projection=(("value_1", "$"),),
    ),
    CaseCoverage(
        case_id="detail-products",
        component_type="detail_table",
        disposition="execute",
        dimensions=("product_key", "product_name"),
        measures=(
            GROSS_SUM,
            CoverageMeasure("cost_amount", AggregateFunction.SUM),
            CoverageMeasure("quantity", AggregateFunction.SUM),
            CoverageMeasure("sales_id", AggregateFunction.COUNT),
            CoverageMeasure("order_id", AggregateFunction.COUNT_DISTINCT),
        ),
        sort_dimension=True,
        golden_projection=(
            ("column_1", "product_key"),
            ("column_2", "product_name"),
            ("value_1", "gross_amount"),
            ("value_2", "cost_amount"),
            ("value_3", "quantity"),
            ("value_4", "row_count"),
            ("value_5", "distinct_order_count"),
        ),
    ),
    CaseCoverage(
        case_id="ranking-products-top2",
        component_type="ranking_table",
        disposition="execute",
        dimensions=("product_key",),
        measures=(GROSS_SUM,),
        top_n=2,
        golden_projection=(("dimension", "product_key"), ("value_1", "gross_amount")),
    ),
    CaseCoverage(
        case_id="bar-category",
        component_type="bar",
        disposition="execute",
        dimensions=("category",),
        measures=(GROSS_SUM,),
        sort_dimension=True,
        golden_projection=(("dimension", "category"), ("value_1", "gross_amount")),
    ),
    CaseCoverage(
        case_id="horizontal-bar-region",
        component_type="horizontal_bar",
        disposition="execute",
        dimensions=("region_name",),
        measures=(GROSS_SUM,),
        sort_dimension=True,
        golden_projection=(("dimension", "region_name"), ("value_1", "gross_amount")),
    ),
    CaseCoverage(
        case_id="stacked-category-region",
        component_type="stacked_bar",
        disposition="execute",
        dimensions=("category",),
        measures=(GROSS_SUM,),
        series_dimension="region_name",
        max_series=4,
        sort_dimension=True,
        golden_projection=(
            ("dimension", "category"),
            ("series", "region_name"),
            ("value_1", "gross_amount"),
        ),
    ),
    CaseCoverage(
        case_id="line-month",
        component_type="line",
        disposition="gap",
        dimensions=("sold_on",),
        measures=(GROSS_SUM,),
        time_grain="month",
        expected_gap_code="time_grain_not_supported",
    ),
    CaseCoverage(
        case_id="area-month",
        component_type="area",
        disposition="gap",
        dimensions=("sold_on",),
        measures=(GROSS_SUM,),
        time_grain="month",
        expected_gap_code="time_grain_not_supported",
    ),
    CaseCoverage(
        case_id="pie-category",
        component_type="pie",
        disposition="execute",
        dimensions=("category",),
        measures=(GROSS_SUM,),
        sort_dimension=True,
        golden_projection=(("dimension", "category"), ("value_1", "gross_amount")),
    ),
    CaseCoverage(
        case_id="donut-category",
        component_type="donut",
        disposition="execute",
        dimensions=("category",),
        measures=(GROSS_SUM,),
        sort_dimension=True,
        golden_projection=(("dimension", "category"), ("value_1", "gross_amount")),
    ),
)
