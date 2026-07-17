from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Column, MetaData, Table, and_, select, union_all
from sqlalchemy.exc import DBAPIError, NoSuchTableError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import FromClause

from bi_system.db.models import (
    Dataset,
    DatasetField,
    ImportColumn,
    ImportTarget,
    Metric,
    MetricDimension,
    SemanticModel,
    SemanticModelJoin,
    SemanticModelJoinKey,
    SemanticModelSource,
)
from bi_system.identity import QueryPrincipal
from bi_system.modeling.calculated_field_contracts import calculated_expression_field_ids
from bi_system.modeling.compiler import (
    CompiledQuery,
    QueryCompilationError,
    QueryCompiler,
    ResolvedMetricSelection,
    ResolvedSource,
)
from bi_system.modeling.contracts import DatasetQueryRequest
from bi_system.modeling.datasets import validate_calculated_field_graph
from bi_system.modeling.expression import LogicalPredicate
from bi_system.modeling.metric_contracts import metric_field_ids, parse_metric_expression
from bi_system.modeling.query_timeout import dataset_query_deadline, is_query_timeout_error
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


class DatasetQueryTimeoutError(DatasetQueryError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedDatasetQuery:
    dataset: Dataset
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

    source = _resolve_joined_source(
        session,
        semantic_model_id=dataset.semantic_model_id,
        workspace_id=principal.workspace_id,
        dataset_fields=dataset_fields,
        referenced_fields=referenced_fields,
    )
    compiler = QueryCompiler(dialect_name=session.get_bind().dialect.name)
    source = _compile_calculated_fields(
        dataset_fields=dataset_fields,
        source=source,
        compiler=compiler,
    )
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
    timeout_seconds: float = 10,
) -> DatasetQueryResult:
    started = perf_counter()
    prepared = validate_dataset_query(session, principal=principal, request=request)
    bounded_statement = prepared.compiled.statement.limit(request.limit + 1)
    batch_filter = prepared.compiled.statement.whereclause
    if batch_filter is None:
        raise DatasetQueryValidationError(
            "compiled_query_filter_missing",
            "Compiled query is missing its mandatory source filter",
            "Validate the dataset query configuration",
        )
    batch_selects = [
        select(batch_column.label("batch_id"))
        .select_from(prepared.source.selectable)
        .where(batch_filter, batch_column.is_not(None))
        for batch_column in prepared.source.batch_columns
    ]
    if not batch_selects:
        raise DatasetQueryValidationError(
            "compiled_query_batch_context_missing",
            "Compiled query does not expose source batch context",
            "Repair the dataset source configuration",
        )
    batch_union = union_all(*batch_selects).subquery()
    try:
        with dataset_query_deadline(session, timeout_seconds=timeout_seconds):
            result_rows = session.execute(bounded_statement).mappings().all()
            truncated = len(result_rows) > request.limit
            rows = tuple(dict(row) for row in result_rows[: request.limit])
            batch_rows = session.scalars(
                select(batch_union.c.batch_id)
                .distinct()
                .order_by(batch_union.c.batch_id)
                .limit(1_001)
            ).all()
    except DBAPIError as exc:
        if not is_query_timeout_error(exc):
            raise
        session.rollback()
        raise DatasetQueryTimeoutError(
            "dataset_query_timeout",
            "Dataset query exceeded its execution deadline",
            "Reduce the query scope or ask an administrator to increase the timeout",
        ) from exc
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


def _resolve_joined_source(
    session: Session,
    *,
    semantic_model_id: UUID,
    workspace_id: UUID,
    dataset_fields: Sequence[DatasetField],
    referenced_fields: list[DatasetField],
) -> ResolvedSource:
    model_sources = session.scalars(
        select(SemanticModelSource)
        .where(SemanticModelSource.semantic_model_id == semantic_model_id)
        .order_by(SemanticModelSource.ordinal, SemanticModelSource.id)
    ).all()
    source_ids = {source.id for source in model_sources}
    if not 1 <= len(model_sources) <= 8 or len(source_ids) != len(model_sources):
        raise _topology_error("Semantic model must contain between one and eight unique sources")
    if len({source.ordinal for source in model_sources}) != len(model_sources):
        raise _topology_error("Semantic model source ordinals must be unique")
    if any(re.fullmatch(r"[a-z][a-z0-9_]{0,62}", source.alias) is None for source in model_sources):
        raise _topology_error("Semantic model source aliases are invalid")
    if len({source.alias for source in model_sources}) != len(model_sources):
        raise _topology_error("Semantic model source aliases must be unique")
    fact_sources = [source for source in model_sources if source.source_role == "fact"]
    if len(fact_sources) != 1 or any(
        source.source_role not in {"fact", "dimension"} for source in model_sources
    ):
        raise _topology_error("Semantic model must contain exactly one fact source")
    fact_source = fact_sources[0]

    target_ids = {source.target_id for source in model_sources}
    targets = session.scalars(
        select(ImportTarget).where(
            ImportTarget.id.in_(target_ids),
            ImportTarget.workspace_id == workspace_id,
            ImportTarget.status == "active",
        )
    ).all()
    targets_by_id = {target.id: target for target in targets}
    if len(targets_by_id) != len(target_ids):
        raise DatasetQueryNotFoundError(
            "dataset_source_not_found",
            "One or more active dataset sources were not found",
            "Repair the dataset source configuration",
        )

    import_columns = session.scalars(
        select(ImportColumn).where(ImportColumn.target_id.in_(target_ids))
    ).all()
    columns_by_id = {column.id: column for column in import_columns}
    tables_by_source_id: dict[UUID, FromClause] = {}
    physical_tables_by_source_id: dict[UUID, Table] = {}
    for source in model_sources:
        target = targets_by_id[source.target_id]
        try:
            physical_table = Table(
                target.physical_table_name,
                MetaData(),
                autoload_with=session.get_bind(),
            )
        except NoSuchTableError as exc:
            raise DatasetQueryValidationError(
                "dataset_source_table_missing",
                "A dataset source table is unavailable",
                "Restore or re-import the dataset source",
            ) from exc
        table = physical_table.alias(source.alias)
        if "_active" not in table.c or "_batch_id" not in table.c:
            raise DatasetQueryValidationError(
                "dataset_source_table_invalid",
                "A dataset source table is missing required system columns",
                "Re-import the dataset source",
            )
        tables_by_source_id[source.id] = table
        physical_tables_by_source_id[source.id] = physical_table

    source_by_id = {source.id: source for source in model_sources}
    joins = session.scalars(
        select(SemanticModelJoin)
        .where(SemanticModelJoin.semantic_model_id == semantic_model_id)
        .order_by(SemanticModelJoin.ordinal, SemanticModelJoin.id)
    ).all()
    if len(joins) != len(model_sources) - 1:
        raise _topology_error("Semantic model joins must form one connected acyclic graph")
    if len({join.ordinal for join in joins}) != len(joins):
        raise _topology_error("Semantic model join ordinals must be unique")

    join_ids = [join.id for join in joins]
    join_keys: list[SemanticModelJoinKey] = []
    if join_ids:
        join_keys = list(
            session.scalars(
                select(SemanticModelJoinKey)
                .where(SemanticModelJoinKey.semantic_model_join_id.in_(join_ids))
                .order_by(
                    SemanticModelJoinKey.semantic_model_join_id,
                    SemanticModelJoinKey.ordinal,
                )
            ).all()
        )
    keys_by_join: dict[UUID, list[SemanticModelJoinKey]] = {join_id: [] for join_id in join_ids}
    for key in join_keys:
        keys_by_join.setdefault(key.semantic_model_join_id, []).append(key)

    source_pairs: set[frozenset[UUID]] = set()
    pending: list[tuple[SemanticModelJoin, ColumnElement[bool]]] = []
    for join in joins:
        if (
            join.left_source_id not in source_ids
            or join.right_source_id not in source_ids
            or join.left_source_id == join.right_source_id
            or join.join_type not in {"inner", "left"}
            or join.cardinality not in {"one_to_one", "many_to_one"}
        ):
            raise _topology_error("Stored semantic model join topology is invalid")
        source_pair = frozenset((join.left_source_id, join.right_source_id))
        if source_pair in source_pairs:
            raise _topology_error("A semantic model source pair may be joined only once")
        source_pairs.add(source_pair)

        keys = keys_by_join.get(join.id, [])
        if not 1 <= len(keys) <= 8 or len({key.ordinal for key in keys}) != len(keys):
            raise _join_key_error("Every semantic model join requires ordered join keys")
        key_pairs = {(key.left_column_id, key.right_column_id) for key in keys}
        if len(key_pairs) != len(keys):
            raise _join_key_error("Semantic model join key pairs must be unique")
        left_source = source_by_id[join.left_source_id]
        right_source = source_by_id[join.right_source_id]
        left_table = tables_by_source_id[left_source.id]
        right_table = tables_by_source_id[right_source.id]
        predicates: list[ColumnElement[bool]] = []
        for key in keys:
            left_column = columns_by_id.get(key.left_column_id)
            right_column = columns_by_id.get(key.right_column_id)
            if (
                left_column is None
                or right_column is None
                or left_column.target_id != left_source.target_id
                or right_column.target_id != right_source.target_id
                or left_column.data_type != right_column.data_type
                or left_column.physical_name not in left_table.c
                or right_column.physical_name not in right_table.c
            ):
                raise _join_key_error(
                    "Join keys must belong to their declared sources and use compatible types"
                )
            predicates.append(
                left_table.c[left_column.physical_name] == right_table.c[right_column.physical_name]
            )
        pending.append((join, and_(*predicates)))

    fact_table = tables_by_source_id[fact_source.id]
    from_clause = fact_table
    joined_source_ids = {fact_source.id}
    while pending:
        progressed = False
        for index, (join, join_predicate) in enumerate(pending):
            left_joined = join.left_source_id in joined_source_ids
            right_joined = join.right_source_id in joined_source_ids
            if left_joined and right_joined:
                raise _topology_error("Semantic model joins contain a cycle")
            if not left_joined and not right_joined:
                continue
            if not left_joined:
                raise _topology_error(
                    "Joins must point from the fact-connected graph to a dimension"
                )
            new_source_id = join.right_source_id
            new_source = source_by_id[new_source_id]
            if new_source.source_role != "dimension":
                raise _topology_error("Only dimension sources may be attached to the fact source")
            new_table = tables_by_source_id[new_source_id]
            on_clause = and_(join_predicate, new_table.c._active.is_(True))
            from_clause = from_clause.join(
                new_table,
                on_clause,
                isouter=join.join_type == "left",
            )
            joined_source_ids.add(new_source_id)
            pending.pop(index)
            progressed = True
            break
        if not progressed:
            raise _topology_error("Semantic model joins are disconnected")
    if joined_source_ids != source_ids:
        raise _topology_error("Semantic model joins do not connect every source")

    resolved_fields: dict[UUID, Column[Any]] = {}
    for field in dataset_fields:
        if field.field_kind != "source":
            continue
        model_source = (
            source_by_id.get(field.model_source_id) if field.model_source_id is not None else None
        )
        import_column = (
            columns_by_id.get(field.source_column_id)
            if field.source_column_id is not None
            else None
        )
        if (
            model_source is None
            or import_column is None
            or import_column.target_id != model_source.target_id
        ):
            continue
        table = tables_by_source_id[model_source.id]
        if import_column.physical_name in table.c:
            resolved_fields[field.id] = cast(Column[Any], table.c[import_column.physical_name])
    if any(
        field.field_kind == "source" and field.id not in resolved_fields
        for field in referenced_fields
    ):
        raise DatasetQueryValidationError(
            "dataset_field_source_mismatch",
            "A dataset field does not belong to its declared model source",
            "Repair the dataset field mapping",
        )

    ordered_tables = tuple(tables_by_source_id[source.id] for source in model_sources)
    return ResolvedSource(
        source_id=fact_source.id,
        table=physical_tables_by_source_id[fact_source.id],
        fields=resolved_fields,
        from_clause=from_clause,
        tables=ordered_tables,
        mandatory_predicates=(fact_table.c._active.is_(True),),
        batch_columns=tuple(cast(Column[Any], table.c._batch_id) for table in ordered_tables),
    )


def _compile_calculated_fields(
    *,
    dataset_fields: Sequence[DatasetField],
    source: ResolvedSource,
    compiler: QueryCompiler,
) -> ResolvedSource:
    try:
        parsed_expressions = validate_calculated_field_graph(list(dataset_fields))
    except ValueError as exc:
        raise DatasetQueryValidationError(
            "calculated_field_configuration_invalid",
            "A calculated field has an invalid dependency or type configuration",
            "Create a corrected dataset version",
        ) from exc
    fields_by_id = {field.id: field for field in dataset_fields}
    dependencies = {
        field_id: {
            dependency_id
            for dependency_id in calculated_expression_field_ids(expression)
            if dependency_id in parsed_expressions
        }
        for field_id, expression in parsed_expressions.items()
    }
    resolved_fields = dict(source.fields)
    resolved_calculated_ids: set[UUID] = set()
    pending_ids = set(parsed_expressions)
    while pending_ids:
        ready_ids = sorted(
            (
                field_id
                for field_id in pending_ids
                if dependencies[field_id].issubset(resolved_calculated_ids)
            ),
            key=str,
        )
        if not ready_ids:
            raise DatasetQueryValidationError(
                "calculated_field_configuration_invalid",
                "Calculated field dependencies contain a cycle",
                "Create a corrected dataset version",
            )
        for field_id in ready_ids:
            field = fields_by_id[field_id]
            compilation_source = replace(
                source,
                fields=resolved_fields,
                calculated_field_ids=frozenset(resolved_calculated_ids),
            )
            try:
                compiled = compiler.compile_calculated_expression(
                    parsed_expressions[field_id],
                    compilation_source,
                    data_type=field.data_type,
                )
            except (QueryCompilationError, ValueError) as exc:
                raise DatasetQueryValidationError(
                    "calculated_field_configuration_invalid",
                    "A calculated field expression cannot be compiled",
                    "Create a corrected dataset version",
                ) from exc
            resolved_fields[field_id] = compiled
            resolved_calculated_ids.add(field_id)
            pending_ids.remove(field_id)
    return replace(
        source,
        fields=resolved_fields,
        calculated_field_ids=frozenset(resolved_calculated_ids),
    )


def _topology_error(message: str) -> DatasetQueryValidationError:
    return DatasetQueryValidationError(
        "semantic_model_topology_invalid",
        message,
        "Repair and reactivate the semantic model",
    )


def _join_key_error(message: str) -> DatasetQueryValidationError:
    return DatasetQueryValidationError(
        "semantic_model_join_key_invalid",
        message,
        "Repair the semantic model join keys",
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
