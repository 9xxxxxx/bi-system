from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportColumn,
    ImportTarget,
    Metric,
    MetricDimension,
    SemanticModel,
    SemanticModelSource,
)
from bi_system.identity import QueryPrincipal
from bi_system.modeling.compiler import (
    CompiledQuery,
    QueryCompilationError,
    QueryCompiler,
    ResolvedMetricSelection,
    ResolvedSource,
)
from bi_system.modeling.contracts import DatasetQueryRequest
from bi_system.modeling.expression import LogicalPredicate
from bi_system.modeling.metric_contracts import metric_field_ids, parse_metric_expression
from bi_system.modeling.row_policies import (
    RowPolicyConfigurationError,
    resolve_row_policy_predicates,
)


class DatasetQueryError(ValueError):
    def __init__(self, code: str, message: str, action: str) -> None:
        super().__init__(message)
        self.code = code
        self.action = action


class DatasetQueryNotFoundError(DatasetQueryError):
    pass


class DatasetQueryForbiddenError(DatasetQueryError):
    pass


class DatasetQueryValidationError(DatasetQueryError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedDatasetQuery:
    dataset: Dataset
    table: Table
    source: ResolvedSource
    compiled: CompiledQuery
    policy_predicates: tuple[ColumnElement[bool], ...]
    metric_version_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class DatasetQueryResult:
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    truncated: bool
    elapsed_ms: float
    dataset_version: int
    metric_version_ids: tuple[UUID, ...]
    source_batch_ids: tuple[UUID, ...]


def validate_dataset_query(
    session: Session,
    *,
    principal: QueryPrincipal,
    request: DatasetQueryRequest,
) -> PreparedDatasetQuery:
    dataset = session.get(Dataset, request.dataset_id)
    if (
        dataset is None
        or dataset.workspace_id != principal.workspace_id
        or dataset.status == "deleted"
        or dataset.deleted_at is not None
    ):
        raise DatasetQueryNotFoundError(
            "dataset_not_found",
            "Dataset was not found",
            "Choose a dataset from the current workspace",
        )
    if not principal.has_permission("datasets:query"):
        raise DatasetQueryForbiddenError(
            "dataset_query_forbidden",
            "Dataset query permission is required",
            "Ask a workspace administrator for query permission",
        )

    semantic_model = session.get(SemanticModel, dataset.semantic_model_id)
    if (
        semantic_model is None
        or semantic_model.workspace_id != principal.workspace_id
        or semantic_model.status == "deleted"
        or semantic_model.deleted_at is not None
    ):
        raise DatasetQueryNotFoundError(
            "dataset_model_not_found",
            "Dataset semantic model was not found",
            "Repair the dataset model configuration",
        )

    model_sources = session.scalars(
        select(SemanticModelSource)
        .where(SemanticModelSource.semantic_model_id == dataset.semantic_model_id)
        .order_by(SemanticModelSource.ordinal),
    ).all()
    if len(model_sources) != 1:
        raise DatasetQueryValidationError(
            "dataset_query_multiple_sources_unsupported",
            "This query endpoint currently supports datasets with one source",
            "Use a single-source dataset until joined query execution is available",
        )
    model_source = model_sources[0]
    target = session.get(ImportTarget, model_source.target_id)
    if target is None or target.workspace_id != principal.workspace_id or target.status != "active":
        raise DatasetQueryNotFoundError(
            "dataset_source_not_found",
            "Dataset source was not found",
            "Repair the dataset source configuration",
        )

    dataset_fields = session.scalars(
        select(DatasetField).where(DatasetField.dataset_id == dataset.id),
    ).all()
    fields_by_id = {field.id: field for field in dataset_fields}
    resolved_metrics, metric_formula_field_ids = _resolve_metrics(
        session,
        request=request,
        workspace_id=principal.workspace_id,
        dataset_id=dataset.id,
    )
    referenced_ids = _referenced_dataset_field_ids(request)
    if not metric_formula_field_ids.issubset(fields_by_id):
        raise DatasetQueryValidationError(
            "metric_field_not_found",
            "An active metric references a field outside its dataset version",
            "Create a corrected metric version",
        )
    referenced_ids.update(metric_formula_field_ids)
    if not referenced_ids.issubset(fields_by_id):
        raise DatasetQueryNotFoundError(
            "dataset_field_not_found",
            "One or more dataset fields were not found",
            "Choose fields from the selected dataset",
        )
    referenced_fields = [fields_by_id[field_id] for field_id in referenced_ids]
    if any(field.field_kind != "source" for field in referenced_fields):
        raise DatasetQueryValidationError(
            "calculated_field_query_unsupported",
            "Calculated fields are not supported by this query endpoint yet",
            "Use source fields until calculated field compilation is available",
        )

    source_fields = [
        field
        for field in dataset_fields
        if field.field_kind == "source"
        and field.model_source_id == model_source.id
        and field.source_column_id is not None
    ]
    import_column_ids = {field.source_column_id for field in source_fields}
    import_columns = session.scalars(
        select(ImportColumn).where(ImportColumn.id.in_(import_column_ids)),
    ).all()
    import_columns_by_id = {column.id: column for column in import_columns}
    for field in referenced_fields:
        source_column_id = field.source_column_id
        if field.model_source_id != model_source.id or source_column_id is None:
            raise DatasetQueryValidationError(
                "dataset_field_source_mismatch",
                "Dataset field does not belong to the query source",
                "Repair the dataset field mapping",
            )
        column = import_columns_by_id.get(source_column_id)
        if column is None or column.target_id != target.id:
            raise DatasetQueryValidationError(
                "dataset_field_source_mismatch",
                "Dataset field does not belong to the query source",
                "Repair the dataset field mapping",
            )

    try:
        table = Table(
            target.physical_table_name,
            MetaData(),
            autoload_with=session.get_bind(),
        )
    except NoSuchTableError as exc:
        raise DatasetQueryValidationError(
            "dataset_source_table_missing",
            "Dataset source table is unavailable",
            "Restore or re-import the dataset source",
        ) from exc
    if "_active" not in table.c or "_batch_id" not in table.c:
        raise DatasetQueryValidationError(
            "dataset_source_table_invalid",
            "Dataset source table is missing required system columns",
            "Re-import the dataset source",
        )

    resolved_fields: dict[UUID, Column[Any]] = {}
    for field in source_fields:
        source_column_id = field.source_column_id
        if source_column_id is None:
            continue
        import_column = import_columns_by_id.get(source_column_id)
        if import_column is None or import_column.physical_name not in table.c:
            continue
        resolved_fields[field.id] = table.c[import_column.physical_name]
    source = ResolvedSource(source_id=model_source.id, table=table, fields=resolved_fields)
    compiler = QueryCompiler(dialect_name=session.get_bind().dialect.name)
    try:
        policy_predicates = tuple(
            resolve_row_policy_predicates(
                session,
                dataset_id=dataset.id,
                workspace_id=principal.workspace_id,
                principal=principal,
                compiler=compiler,
                source=source,
            ),
        )
        compiled = compiler.compile_dataset_query(
            request,
            source,
            metrics=resolved_metrics,
            policy_predicates=policy_predicates,
        )
    except QueryCompilationError as exc:
        raise DatasetQueryValidationError(
            exc.code,
            str(exc),
            "Correct the query fields, filters, or aggregation",
        ) from exc
    except RowPolicyConfigurationError as exc:
        raise DatasetQueryValidationError(
            "row_policy_configuration_invalid",
            "An active row policy is invalid",
            "Ask a data administrator to repair the row policy",
        ) from exc
    return PreparedDatasetQuery(
        dataset=dataset,
        table=table,
        source=source,
        compiled=compiled,
        policy_predicates=policy_predicates,
        metric_version_ids=tuple(metric.metric_version_id for metric in resolved_metrics),
    )


def execute_dataset_query(
    session: Session,
    *,
    principal: QueryPrincipal,
    request: DatasetQueryRequest,
) -> DatasetQueryResult:
    started = perf_counter()
    prepared = validate_dataset_query(session, principal=principal, request=request)
    bounded_statement = prepared.compiled.statement.limit(request.limit + 1)
    result_rows = session.execute(bounded_statement).mappings().all()
    truncated = len(result_rows) > request.limit
    rows = tuple(dict(row) for row in result_rows[: request.limit])

    batch_filter = prepared.compiled.statement.whereclause
    if batch_filter is None:
        raise DatasetQueryValidationError(
            "compiled_query_filter_missing",
            "Compiled query is missing its mandatory source filter",
            "Validate the dataset query configuration",
        )
    batch_rows = session.scalars(
        select(prepared.table.c._batch_id)
        .where(batch_filter)
        .distinct()
        .order_by(prepared.table.c._batch_id)
        .limit(1_001),
    ).all()
    if len(batch_rows) > 1_000:
        raise DatasetQueryValidationError(
            "source_batch_limit_exceeded",
            "Dataset query spans too many source batches",
            "Compact or replace the source data before querying",
        )
    elapsed_ms = round((perf_counter() - started) * 1000, 3)
    return DatasetQueryResult(
        columns=prepared.compiled.output_names,
        rows=rows,
        truncated=truncated,
        elapsed_ms=elapsed_ms,
        dataset_version=prepared.dataset.version,
        metric_version_ids=prepared.metric_version_ids,
        source_batch_ids=tuple(
            batch_id if isinstance(batch_id, UUID) else UUID(str(batch_id))
            for batch_id in batch_rows
        ),
    )


def _referenced_dataset_field_ids(request: DatasetQueryRequest) -> set[UUID]:
    field_ids = {selection.field_id for selection in request.selections}
    field_ids.update(request.group_by)
    field_ids.update(sort.field_id for sort in request.order_by)
    expression = request.filter
    if expression is not None:
        predicates = (
            expression.predicates if isinstance(expression, LogicalPredicate) else (expression,)
        )
        field_ids.update(predicate.field_id for predicate in predicates)
    return field_ids


def _resolve_metrics(
    session: Session,
    *,
    request: DatasetQueryRequest,
    workspace_id: UUID,
    dataset_id: UUID,
) -> tuple[tuple[ResolvedMetricSelection, ...], set[UUID]]:
    if not request.metrics:
        return (), set()
    requested_ids = [selection.metric_id for selection in request.metrics]
    metrics = session.scalars(
        select(Metric).where(
            Metric.id.in_(requested_ids),
            Metric.workspace_id == workspace_id,
            Metric.dataset_id == dataset_id,
            Metric.status == "active",
            Metric.deleted_at.is_(None),
        )
    ).all()
    metrics_by_id = {metric.id: metric for metric in metrics}
    if len(metrics_by_id) != len(set(requested_ids)):
        raise DatasetQueryNotFoundError(
            "metric_not_found",
            "One or more active metric versions were not found for the dataset",
            "Choose active metrics from the selected dataset version",
        )

    dimension_rows = session.execute(
        select(MetricDimension.metric_id, MetricDimension.dataset_field_id).where(
            MetricDimension.metric_id.in_(requested_ids)
        )
    ).all()
    dimensions_by_metric: dict[UUID, set[UUID]] = {metric_id: set() for metric_id in requested_ids}
    for metric_id, field_id in dimension_rows:
        dimensions_by_metric[metric_id].add(field_id)
    group_fields = set(request.group_by)
    for metric_id in requested_ids:
        if not group_fields.issubset(dimensions_by_metric[metric_id]):
            raise DatasetQueryValidationError(
                "metric_group_by_not_allowed",
                "Query group fields are not declared dimensions of every metric",
                "Remove unsupported group fields or create a metric version with those dimensions",
            )

    resolved: list[ResolvedMetricSelection] = []
    formula_field_ids: set[UUID] = set()
    for selection in request.metrics:
        metric = metrics_by_id[selection.metric_id]
        try:
            formula = parse_metric_expression(metric.formula)
        except ValidationError as exc:
            raise DatasetQueryValidationError(
                "metric_formula_invalid",
                "An active metric has an invalid formula",
                "Create a corrected metric version",
            ) from exc
        formula_field_ids.update(metric_field_ids(formula))
        resolved.append(
            ResolvedMetricSelection(
                metric_version_id=metric.id,
                output_name=selection.output_name,
                formula=formula,
            )
        )
    return tuple(resolved), formula_field_ids
