# M3 Chart Query Compiler Spike

## Decision summary

Status: **conditionally viable for M3 contract freeze** (2026-07-18).

The spike proves that the M3 core chart slots can compile into the accepted M2
`DatasetQueryRequest` without accepting physical table names, physical column names, SQL, or
arbitrary functions. Dataset, field, and metric-version references remain UUIDs until the existing
M2 query service resolves workspace ownership, active versions, metric dimensions, RLS, active
batch predicates, limits, and timeout behavior.

Do not copy the spike into production as-is. Production work needs the frozen chart contract and
server-owned resource catalog resolution. The updated M3 architecture freezes the remaining M2
gaps as M3-R2 extensions or explicit refusals. In particular, metric Top N is not representable by
the current `QuerySort` contract and the spike returns `metric_sort_not_supported` rather than
weakening the query boundary.

Runnable source is under `spikes/m3/backend/`. No production source, migration, route, or
dependency was changed.

## Existing M2 boundary used

The spike compiles only to `backend/src/bi_system/modeling/contracts.py::DatasetQueryRequest`.
The resulting request retains these M2 constraints:

- Pydantic models use `extra="forbid"`; unknown capabilities such as `raw_sql` are rejected.
- `dataset_id`, `field_id`, and the current metric selection ID are UUIDs. The M2 query service
  confirms that `DatasetMetricSelection.metric_id` identifies an active metric version in the
  selected dataset and workspace.
- Non-aggregate selections exactly match `group_by`; sort expressions must be selected.
- Filters use the discriminated M2 comparison, set, null, text, or flat logical expression union.
- The query service and `QueryCompiler` remain responsible for field resolution, metric formula
  resolution, metric-dimension compatibility, RLS, `_active`, bound values, result limits, and
  dialect-safe SQLAlchemy compilation.

The M3 config intentionally calls the metric reference `metric_version_id`; it maps to the legacy
M2 `DatasetMetricSelection.metric_id` member at the boundary. Production naming should remove this
semantic mismatch without changing the persisted identity.

## Spike contract

`ResourceCatalog` represents only server-resolved, authorized resources:

| Resource | Accepted identity | Metadata used by chart compilation |
| --- | --- | --- |
| Dataset | `dataset_id: UUID` | Must equal the resolved catalog dataset |
| Field | `field_id: UUID` | Role, logical data type and server-resolved primary/series cardinality when applicable |
| Metric version | `metric_version_id: UUID` | Membership in resolved active metric versions |

Generated output names (`dimension`, `value_1`, `column_1`, and so on) are server-owned. Clients do
not provide output aliases, expression functions, table names, or column names. Field measures can
choose only the six M2 aggregate enum values: `sum`, `avg`, `count`, `count_distinct`, `min`, and
`max`. Numeric-only aggregates are rejected before reaching M2.

Top N is limited to 1-100, requires descending value order, and adds the dimension as an ascending
secondary sort for deterministic ties. Non-Top-N detail queries retain the M2 1-10,000 row limit.
Series dimensions compile to a second non-aggregate selection/group field only when the authorized
catalog supplies cardinality evidence for both grouping fields, the series cardinality is within
`max_series`, and their product fits the effective `query_limit` (default 500, range 1-10,000).
Series plus Top N is rejected before M2. After M2 execution, the chart boundary rejects a truncated
result or a row count above the resolved product instead of rendering a partial/stale series group.

## Support matrix

| Chart | Required slots | M2 mapping | Sort / Top N | Spike result |
| --- | --- | --- | --- | --- |
| KPI | Exactly one field aggregate or metric version | Aggregate selection or metric selection; limit 1 | None | Supported |
| Detail table | 1-50 unique fields and up to 50 values | Raw selections or grouped fields plus aggregates/metrics | Selected field; limit 1-10,000 | Supported |
| Ranking table | One dimension and one value | Group field plus aggregate/metric | Descending value, Top N 1-100 | Field aggregate supported; metric blocked by M2 |
| Bar / horizontal bar | One dimension and 1-10 values | Group field plus aggregates/metrics | Dimension or value; optional Top N | Supported except metric value sort |
| Stacked bar | One dimension plus 2-10 values, or one value plus bounded series dimension | One or two group fields plus aggregates/metrics | Series forbids Top N and requires a complete product bound | Multi-measure and complete series-dimension stacks supported |
| Line | One dimension and 1-10 values | Group field plus aggregates/metrics | Dimension or value; optional Top N | Raw dimension supported; time grain is an M3-R2 gap |
| Area | One dimension and 1-10 values | Group field plus aggregates/metrics | Dimension or value; optional Top N | Raw dimension supported; time grain is an M3-R2 gap |
| Pie / donut | One dimension and one value | Group field plus aggregate/metric | Dimension or value; optional Top N | Supported except metric value sort |
| Filter | M2 filter expression using field UUIDs | Passed unchanged after catalog membership check | Up to M2 predicate limit | Supported |

“Supported” means contract compilation is proven; execution still goes through M2 authorization and
resource resolution. A chart config alone is never executable SQL.

## Error matrix

| Code | Trigger | Owning layer |
| --- | --- | --- |
| `chart_config_invalid` | Missing/extra slot, unknown chart type, invalid UUID/enum, illegal cardinality, Top N outside 1-100 | M3 schema |
| `dataset_not_resolved` | Dataset UUID differs from authorized catalog | M3 compiler |
| `field_not_resolved` | Dimension, value, column, sort, or filter field absent from catalog | M3 compiler |
| `metric_version_not_resolved` | Metric version absent from active authorized catalog | M3 compiler |
| `invalid_dimension_role` | Measure field placed in a dimension slot | M3 compiler |
| `invalid_aggregate_type` | `sum`/`avg`/`min`/`max` on a nonnumeric field | M3 compiler, repeated by M2 |
| `duplicate_value` | Duplicate resource and aggregate pair in value slots | M3 compiler |
| `sort_value_not_selected` | Value sort index is outside selected values | M3 compiler |
| `top_n_requires_value_sort` | Top N combined with dimension sorting | M3 compiler |
| `top_n_requires_descending_sort` | Top N combined with ascending value sorting | M3 compiler |
| `metric_sort_not_supported` | Sort or Top N by a metric version | M2 contract gap |
| `time_grain_not_supported` | Day/week/month/quarter/year grouping requested | M2 contract gap; M3-R2 adapter required |
| `invalid_series_dimension_role` | Measure field placed in a series dimension slot | M3 compiler |
| `duplicate_dimension` | Primary and series dimensions reference the same field | M3 compiler |
| `series_cardinality_not_resolved` | Authorized catalog lacks series cardinality evidence | M3 compiler |
| `series_cardinality_invalid` | Authorized catalog reports a negative grouping cardinality | M3 compiler |
| `series_cardinality_exceeded` | Resolved cardinality exceeds `max_series` | M3 compiler |
| `series_result_limit_exceeded` | Primary cardinality times series cardinality exceeds `query_limit` | M3 compiler |
| `series_result_truncated` | M2 reports truncation for a series query | M3 result boundary |
| `series_cardinality_evidence_stale` | Returned row count exceeds the server-resolved product bound | M3 result boundary |
| `series_top_n_not_supported` | Series dimension combined with Top N | Frozen M3 refusal |
| Existing M2 codes | Invalid filter value/type, disallowed metric dimension, field/version race, RLS/permission, complexity, timeout | M2 service/compiler |

Errors expose `code`, `message`, and optional config `path`. Production HTTP mapping should preserve
stable codes and safe messages while logging the dashboard/component IDs and request correlation ID.

## Security evidence

Negative tests submit `raw_sql`, `table_name`, `column_name`, and `function` properties containing
SQL payloads. Strict chart models reject all four. Filter values remain typed data; the injection
payload `x' OR 1=1 --` is absent from compiled SQL and present only in SQLAlchemy bound parameters.
The compiled M2 statement also contains the mandatory `_active` predicate.

This evidence does not replace authorization tests. The production catalog must be built after
workspace/resource permission checks and must never be accepted from the browser.

## Result equivalence

The representative bar query uses a dimension, `sum` value, `amount > 5` filter, descending value
Top 2, and an inactive high-value row. The chart compiler emits `DatasetQueryRequest`; the unchanged
M2 `QueryCompiler` executes it on SQLite. Actual rows are:

```text
[{"dimension": "A", "value_1": 25}, {"dimension": "B", "value_1": 20}]
```

This matches manual aggregation. The inactive `D=999` row and filtered `C=3` row do not appear.

## C1 chart-case integration

`spikes/m3/backend/case_coverage.py` is the typed, test-enforced mapping between every C1 case and
its UUID-only spike config, expected compile disposition, golden projection, and stable gap code.
The test reads the checked-in `spikes/m3/quality/fixture/v1/chart_cases.json` and
`golden_results.json` directly. It does not duplicate or regenerate C1 files.

The eight currently M2-expressible cases compile through the spike, compile again through the
unchanged M2 `QueryCompiler`, execute on a SQLite table populated from the C1 joined fixture, and
match the selected golden columns exactly. The two month-bucket cases parse as valid M3 intent but
stop at the explicit M2 gap.

| C1 case | Compile | SQLite / golden | Result |
| --- | --- | --- | --- |
| `kpi-gross` | Yes | Executed; exact KPI scalar | Supported now |
| `detail-products` | Yes | Executed; product dimensions and five aggregate golden columns | Supported now |
| `ranking-products-top2` | Yes | Executed; product key and gross Top 2 | Supported now |
| `bar-category` | Yes | Executed; category and gross | Supported now |
| `horizontal-bar-region` | Yes | Executed; region and gross | Supported now |
| `stacked-category-region` | Yes | Executed; category, bounded region series and gross | Supported now |
| `line-month` | Stable gap | Not executed | `time_grain_not_supported`; M3-R2 time adapter |
| `area-month` | Stable gap | Not executed | `time_grain_not_supported`; M3-R2 time adapter |
| `pie-category` | Yes | Executed; category and gross | Supported now |
| `donut-category` | Yes | Executed; category and gross | Supported now |

The C1 detail golden contains additional derived values such as margin and return count. The spike
compares every directly selected field aggregate in its case mapping; derived values remain covered
by C1 generation and require published calculated fields or metric versions in a production dataset.

## Performance

Command:

```text
uv run python -m spikes.m3.backend.benchmark
```

Observed on the current Windows development machine:

```json
{"compiles_per_second": 44375.46, "elapsed_seconds": 0.22535, "iterations": 10000, "microseconds_per_compile": 22.53}
```

This measures schema validation, catalog checks, and M2 request construction only. It excludes
database resource resolution, SQLAlchemy compilation, query execution, serialization, network, and
cache behavior. The compiler overhead is negligible relative to the M3 five-second query target,
but production performance must be measured end-to-end with the C1 fixture and 20-concurrency plan.

## Actual verification

Commands and results after formatting:

```text
uv run pytest spikes/m3/backend -q
29 passed

uv run ruff check spikes/m3/backend
All checks passed!

uv run ruff format --check spikes/m3/backend
6 files already formatted

uv run basedpyright spikes/m3/backend
0 errors, 0 warnings, 0 notes

uv run pytest backend/tests/unit/test_modeling_contracts.py backend/tests/unit/test_modeling_compiler.py spikes/m3/backend -q
45 passed
```

The test suite covers all chart families in the support matrix, field and metric-version mappings,
filters, aggregation, sorting, deterministic Top N, invalid slots, unknown references, invalid
aggregate type, boundary values 1/100 and 0/101, metric-sort refusal, raw capability injection, bound
filter injection, and representative M2 execution.

## Frozen M3-R2 implementation boundary

1. Add a discriminated dataset sort target that can reference either a selected field aggregate or
   selected metric version. The metric case must reuse the already-resolved metric expression; it
   must not accept output-name SQL, a formula from the client, or an arbitrary function.
2. Implement governed day/week/month/quarter/year grouping behind explicit SQLite/PostgreSQL
   adapters. Until then, raw date dimensions work but time-grain requests return the stable gap.
3. Carry primary and series cardinality evidence from server resolution into compilation, enforce
   their product against the effective limit, validate result completeness after execution, and
   retain the frozen refusal of series plus Top N. The spike proves the two-field group shape and
   golden result without partial groups.
4. Do not add an `Others` bucket in M3. Current Top N limits sorted groups and reports truncation;
   no client-side or SQL-special-case aggregation is permitted.
5. Resolve metric dimension compatibility in the server catalog or retain the existing query-service
   validation. Persisted chart configs must report a stable error when a newer metric version removes
   a configured dimension.
6. Define null ordering, tie behavior, timezone, Decimal/date serialization, truncation evidence,
   source batch IDs, and selected metric version IDs in the M3 response contract.
7. Keep config parsing, authorized catalog resolution, M2 compilation, execution, and response
   shaping as separate boundaries. Only the first and last are chart-specific.

M3-R2 may claim series-dimension stacking only with cardinality enforcement. It may claim metric
Top N or time-series buckets only after the corresponding governed M2 extension passes SQLite and
PostgreSQL portability tests. `Others` and series plus Top N remain intentionally unsupported in M3.
