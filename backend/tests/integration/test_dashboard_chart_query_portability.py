from __future__ import annotations

import csv
import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from bi_system.dashboards.chart_contracts import (
    DashboardChartQueryRequest,
    RuntimeChartFilterScopes,
)
from bi_system.dashboards.chart_query import (
    DashboardChartQueryError,
    DashboardChartResult,
    execute_dashboard_chart_query,
    validate_dashboard_chart_query,
)
from bi_system.db.base import Base
from bi_system.db.models import (
    Dashboard,
    DashboardComponent,
    DashboardLayout,
    DashboardPage,
    DashboardPermission,
    DashboardVersion,
    Dataset,
    DatasetField,
    ImportColumn,
    ImportTarget,
    Metric,
    RowPolicy,
    RowPolicyAssignment,
    SemanticModel,
    SemanticModelJoin,
    SemanticModelJoinKey,
    SemanticModelSource,
    User,
)
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Uuid,
    event,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "spikes" / "m3" / "quality" / "fixture" / "v2"
QUERY_PERMISSIONS = frozenset({"dashboards:view", "datasets:query"})


@dataclass(frozen=True, slots=True)
class ChartPortabilityContext:
    engine: Engine
    session_factory: sessionmaker[Session]
    owner: QueryPrincipal
    viewer: QueryPrincipal
    foreign_user: QueryPrincipal
    dashboard_id: UUID
    dashboard_version_id: UUID
    page_id: UUID
    component_ids: dict[str, UUID]
    dataset_id: UUID
    metric_id: UUID
    field_ids: dict[str, UUID]
    batch_ids: frozenset[UUID]
    physical_table_names: frozenset[str]

    def request(
        self,
        component: str,
        *,
        runtime_filters: RuntimeChartFilterScopes | None = None,
    ) -> DashboardChartQueryRequest:
        return DashboardChartQueryRequest(
            dashboard_id=self.dashboard_id,
            dashboard_version_id=self.dashboard_version_id,
            page_id=self.page_id,
            component_id=self.component_ids[component],
            runtime_filters=runtime_filters,
        )


@pytest.fixture
def chart_context(tmp_path: Path) -> Iterator[ChartPortabilityContext]:
    database_url = os.environ.get(
        "BI_DATABASE_URL",
        f"sqlite+pysqlite:///{(tmp_path / 'dashboard-chart-portability.db').as_posix()}",
    )
    with portable_database_engine(database_url) as engine:
        Base.metadata.create_all(engine)
        context = _seed_chart_context(engine)
        yield context


def test_representative_chart_shapes_execute_with_portable_types(
    chart_context: ChartPortabilityContext,
) -> None:
    context = chart_context
    unfiltered = RuntimeChartFilterScopes()
    with context.session_factory() as session:
        for component in ("kpi", "bar", "line", "pie", "detail", "ranking", "stacked"):
            validation = validate_dashboard_chart_query(
                session,
                principal=context.owner,
                request=context.request(component, runtime_filters=unfiltered),
                workspace_timezone="Asia/Hong_Kong",
                timeout_seconds=10,
            )
            assert validation.valid is True
            assert validation.dataset_version == 1

        kpi = _execute(session, context, "kpi", runtime_filters=unfiltered)
        assert kpi.rows == ({"value_1": "2838.74"},)
        assert [column.slot_key for column in kpi.columns] == ["gross"]
        assert kpi.metric_version_ids == (context.metric_id,)
        assert set(kpi.source_batch_ids) == context.batch_ids
        assert kpi.dataset_version == 1
        assert kpi.truncated is False

        bar = _execute(session, context, "bar", runtime_filters=unfiltered)
        pie = _execute(session, context, "pie", runtime_filters=unfiltered)
        assert bar.rows == pie.rows
        assert _dimension_totals(bar) == {
            None: "155.25",
            "Hardware": "2163.50",
            "Services": "519.99",
        }

        line = _execute(session, context, "line", runtime_filters=unfiltered)
        assert [row["value_1"] for row in line.rows] == ["1532.49", "1306.25"]
        assert all(str(row["dimension"]).startswith("2026-0") for row in line.rows)

        detail = _execute(session, context, "detail", runtime_filters=unfiltered)
        assert len(detail.rows) == 14
        assert any(row["dimension_3"] is None for row in detail.rows)
        assert {row["dimension_4"] for row in detail.rows} == {True, False}
        assert all(str(row["dimension_1"]).startswith("2026-") for row in detail.rows)
        assert all("T" in str(row["dimension_2"]) for row in detail.rows)
        assert all(isinstance(row["value_1"], str) for row in detail.rows)

        stacked = _execute(session, context, "stacked", runtime_filters=unfiltered)
        assert len(stacked.rows) == 8
        assert {column.query_alias for column in stacked.columns} == {
            "dimension",
            "series",
            "value_1",
        }


def test_top_n_is_stable_across_repeated_governed_execution(
    chart_context: ChartPortabilityContext,
) -> None:
    expected = (
        {"dimension": "P100", "value_1": "1110.00"},
        {"dimension": "P200", "value_1": "1053.50"},
    )
    with chart_context.session_factory() as session:
        for _ in range(10):
            result = _execute(
                session,
                chart_context,
                "ranking",
                runtime_filters=RuntimeChartFilterScopes(),
            )
            assert result.rows == expected


def test_scoped_filters_resolve_in_order_and_rls_precedes_aggregation(
    chart_context: ChartPortabilityContext,
) -> None:
    context = chart_context
    january = _date_filter(context.field_ids["sold_on"], "2026-01-01", "2026-02-01")
    north = _comparison_filter(context.field_ids["region_key"], "R-NORTH")
    south = _comparison_filter(context.field_ids["region_key"], "R-SOUTH")
    with context.session_factory() as session:
        global_only = _execute(
            session,
            context,
            "kpi",
            runtime_filters=RuntimeChartFilterScopes(global_filter=january),
        )
        assert global_only.rows == ({"value_1": "1532.49"},)

        global_and_page = _execute(
            session,
            context,
            "kpi",
            runtime_filters=RuntimeChartFilterScopes(
                global_filter=january,
                page_filter=north,
            ),
        )
        assert global_and_page.rows == ({"value_1": "530.49"},)

        saved_scopes = _execute(session, context, "kpi")
        assert saved_scopes.rows == ({"value_1": "350.50"},)
        assert [evidence.scope for evidence in saved_scopes.resolved_filters] == [
            "global",
            "page",
            "component",
        ]
        assert all(
            evidence.timezone == "Asia/Hong_Kong" for evidence in saved_scopes.resolved_filters
        )

        restricted = _execute(
            session,
            context,
            "kpi",
            principal=context.viewer,
            runtime_filters=RuntimeChartFilterScopes(),
        )
        assert restricted.rows == ({"value_1": "805.74"},)

        forged = _execute(
            session,
            context,
            "bar",
            principal=context.viewer,
            runtime_filters=RuntimeChartFilterScopes(global_filter=south),
        )
        assert forged.rows == ()


def test_foreign_workspace_is_rejected_before_physical_query(
    chart_context: ChartPortabilityContext,
) -> None:
    physical_query_executed = False

    def observe_physical_query(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal physical_query_executed
        lowered = statement.lower()
        if any(name.lower() in lowered for name in chart_context.physical_table_names):
            physical_query_executed = True

    event.listen(chart_context.engine, "before_cursor_execute", observe_physical_query)
    try:
        with (
            chart_context.session_factory() as session,
            pytest.raises(DashboardChartQueryError) as captured,
        ):
            _execute(
                session,
                chart_context,
                "kpi",
                principal=chart_context.foreign_user,
                runtime_filters=RuntimeChartFilterScopes(),
            )
        assert captured.value.code == "dashboard_not_found"
        assert physical_query_executed is False
    finally:
        event.remove(chart_context.engine, "before_cursor_execute", observe_physical_query)


def _execute(
    session: Session,
    context: ChartPortabilityContext,
    component: str,
    *,
    principal: QueryPrincipal | None = None,
    runtime_filters: RuntimeChartFilterScopes | None = None,
) -> DashboardChartResult:
    return execute_dashboard_chart_query(
        session,
        principal=context.owner if principal is None else principal,
        request=context.request(component, runtime_filters=runtime_filters),
        workspace_timezone="Asia/Hong_Kong",
        timeout_seconds=10,
    )


def _dimension_totals(result: DashboardChartResult) -> dict[object, object]:
    return {row["dimension"]: row["value_1"] for row in result.rows}


@contextmanager
def portable_database_engine(database_url: str) -> Generator[Engine]:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        engine = create_database_engine(database_url)
        try:
            yield engine
        finally:
            engine.dispose()
        return

    schema_name = f"bi_m3_chart_test_{uuid4().hex}"
    administration_engine = create_database_engine(database_url)
    schema_created = False
    try:
        with administration_engine.begin() as connection:
            connection.execute(CreateSchema(schema_name))
        schema_created = True
        isolated_url = url.update_query_dict({"options": f"-csearch_path={schema_name}"})
        engine = create_database_engine(isolated_url.render_as_string(hide_password=False))
        try:
            yield engine
        finally:
            engine.dispose()
    finally:
        if schema_created:
            with administration_engine.begin() as connection:
                connection.execute(DropSchema(schema_name, cascade=True, if_exists=True))
        administration_engine.dispose()


def _seed_chart_context(engine: Engine) -> ChartPortabilityContext:
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    table_names = {
        "sales": f"data_{uuid4().hex}",
        "product": f"data_{uuid4().hex}",
        "region": f"data_{uuid4().hex}",
    }
    tables = _create_physical_tables(engine, table_names)
    batch_ids = _seed_fixture_rows(engine, tables)

    with session_factory.begin() as session:
        users = _add_users(session, workspace_id)
        targets, columns = _add_import_resources(session, workspace_id, table_names)
        model, sources = _add_semantic_model(
            session,
            workspace_id,
            users["owner"].id,
            targets,
            columns,
        )
        dataset, fields, metric = _add_dataset_resources(
            session,
            workspace_id,
            users["owner"].id,
            model,
            sources,
            columns,
        )
        dashboard, version, page, component_ids = _add_dashboard_resources(
            session,
            workspace_id,
            users,
            dataset,
            fields,
            metric,
        )
        _add_row_policies(session, workspace_id, users, dataset, fields)

        owner_id = users["owner"].id
        viewer_id = users["viewer"].id
        foreign_id = users["foreign"].id

    return ChartPortabilityContext(
        engine=engine,
        session_factory=session_factory,
        owner=QueryPrincipal(owner_id, workspace_id, permissions=QUERY_PERMISSIONS),
        viewer=QueryPrincipal(viewer_id, workspace_id, permissions=QUERY_PERMISSIONS),
        foreign_user=QueryPrincipal(foreign_id, uuid4(), permissions=QUERY_PERMISSIONS),
        dashboard_id=dashboard.id,
        dashboard_version_id=version.id,
        page_id=page.page_id,
        component_ids=component_ids,
        dataset_id=dataset.id,
        metric_id=metric.id,
        field_ids={name: field.id for name, field in fields.items()},
        batch_ids=frozenset(batch_ids.values()),
        physical_table_names=frozenset(table_names.values()),
    )


def _create_physical_tables(engine: Engine, names: dict[str, str]) -> dict[str, Table]:
    metadata = MetaData()
    tables = {
        "sales": Table(
            names["sales"],
            metadata,
            *_system_columns(),
            Column("sales_id", Integer, nullable=False),
            Column("order_id", String(32), nullable=False),
            Column("sold_on", Date, nullable=False),
            Column("occurred_at", DateTime(timezone=True), nullable=False),
            Column("product_key", String(32)),
            Column("region_key", String(32), nullable=False),
            Column("quantity", Integer, nullable=False),
            Column("gross_amount", Numeric(12, 2), nullable=False),
            Column("cost_amount", Numeric(12, 2), nullable=False),
            Column("is_returned", Boolean, nullable=False),
            Column("discount_rate", Numeric(5, 2)),
        ),
        "product": Table(
            names["product"],
            metadata,
            *_system_columns(),
            Column("product_key", String(32), nullable=False),
            Column("product_name", String(128), nullable=False),
            Column("category", String(64), nullable=False),
            Column("launch_date", Date, nullable=False),
            Column("is_active", Boolean, nullable=False),
        ),
        "region": Table(
            names["region"],
            metadata,
            *_system_columns(),
            Column("region_key", String(32), nullable=False),
            Column("region_name", String(128), nullable=False),
            Column("region_group", String(64), nullable=False),
            Column("is_restricted", Boolean, nullable=False),
        ),
    }
    metadata.create_all(engine)
    return tables


def _system_columns() -> list[Column[Any]]:
    return [
        Column("_row_id", Uuid(as_uuid=True), primary_key=True),
        Column("_batch_id", Uuid(as_uuid=True), nullable=False),
        Column("_row_number", Integer, nullable=False),
        Column("_active", Boolean, nullable=False),
    ]


def _seed_fixture_rows(engine: Engine, tables: dict[str, Table]) -> dict[str, UUID]:
    batch_ids = {name: uuid4() for name in tables}
    with engine.begin() as connection:
        connection.execute(
            tables["sales"].insert(),
            [
                _system_row(
                    batch_ids["sales"],
                    index,
                    sales_id=int(row["sales_id"]),
                    order_id=row["order_id"],
                    sold_on=date.fromisoformat(row["sold_on"]),
                    occurred_at=_utc_datetime(row["occurred_at"]),
                    product_key=row["product_key"] or None,
                    region_key=row["region_key"],
                    quantity=int(row["quantity"]),
                    gross_amount=Decimal(row["gross_amount"]),
                    cost_amount=Decimal(row["cost_amount"]),
                    is_returned=_bool(row["is_returned"]),
                    discount_rate=(Decimal(row["discount_rate"]) if row["discount_rate"] else None),
                )
                for index, row in enumerate(_csv_rows("fact_sales.csv"), start=1)
            ],
        )
        connection.execute(
            tables["product"].insert(),
            [
                _system_row(
                    batch_ids["product"],
                    index,
                    product_key=row["product_key"],
                    product_name=row["product_name"],
                    category=row["category"],
                    launch_date=date.fromisoformat(row["launch_date"]),
                    is_active=_bool(row["is_active"]),
                )
                for index, row in enumerate(_csv_rows("dim_product.csv"), start=1)
            ],
        )
        connection.execute(
            tables["region"].insert(),
            [
                _system_row(
                    batch_ids["region"],
                    index,
                    region_key=row["region_key"],
                    region_name=row["region_name"],
                    region_group=row["region_group"],
                    is_restricted=_bool(row["is_restricted"]),
                )
                for index, row in enumerate(_csv_rows("dim_region.csv"), start=1)
            ],
        )
    return batch_ids


def _system_row(batch_id: UUID, row_number: int, **values: Any) -> dict[str, Any]:
    return {
        "_row_id": uuid4(),
        "_batch_id": batch_id,
        "_row_number": row_number,
        "_active": True,
        **values,
    }


def _csv_rows(filename: str) -> list[dict[str, str]]:
    with (FIXTURE_ROOT / filename).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _bool(value: str) -> bool:
    return value.lower() == "true"


def _add_users(session: Session, workspace_id: UUID) -> dict[str, User]:
    users = {
        "owner": User(
            workspace_id=workspace_id,
            username=f"chart-owner-{uuid4().hex}",
            display_name="Chart owner",
            password_hash="not-used-in-test",
        ),
        "viewer": User(
            workspace_id=workspace_id,
            username=f"chart-viewer-{uuid4().hex}",
            display_name="Restricted viewer",
            password_hash="not-used-in-test",
        ),
        "foreign": User(
            workspace_id=uuid4(),
            username=f"chart-foreign-{uuid4().hex}",
            display_name="Foreign viewer",
            password_hash="not-used-in-test",
        ),
    }
    session.add_all(users.values())
    session.flush()
    return users


def _add_import_resources(
    session: Session,
    workspace_id: UUID,
    table_names: dict[str, str],
) -> tuple[dict[str, ImportTarget], dict[str, dict[str, ImportColumn]]]:
    targets = {
        name: ImportTarget(
            workspace_id=workspace_id,
            name=f"M3 {name} {uuid4().hex}",
            physical_table_name=table_name,
            status="active",
        )
        for name, table_name in table_names.items()
    }
    session.add_all(targets.values())
    session.flush()
    definitions = {
        "sales": [
            ("sales_id", "integer", False),
            ("order_id", "string", False),
            ("sold_on", "date", False),
            ("occurred_at", "datetime", False),
            ("product_key", "string", True),
            ("region_key", "string", False),
            ("quantity", "integer", False),
            ("gross_amount", "decimal", False),
            ("cost_amount", "decimal", False),
            ("is_returned", "boolean", False),
            ("discount_rate", "decimal", True),
        ],
        "product": [
            ("product_key", "string", False),
            ("product_name", "string", False),
            ("category", "string", False),
            ("launch_date", "date", False),
            ("is_active", "boolean", False),
        ],
        "region": [
            ("region_key", "string", False),
            ("region_name", "string", False),
            ("region_group", "string", False),
            ("is_restricted", "boolean", False),
        ],
    }
    columns: dict[str, dict[str, ImportColumn]] = {}
    for source_name, source_definitions in definitions.items():
        columns[source_name] = {
            name: ImportColumn(
                target_id=targets[source_name].id,
                source_name=name,
                physical_name=name,
                data_type=data_type,
                nullable=nullable,
                ordinal=ordinal,
            )
            for ordinal, (name, data_type, nullable) in enumerate(source_definitions)
        }
        session.add_all(columns[source_name].values())
    session.flush()
    return targets, columns


def _add_semantic_model(
    session: Session,
    workspace_id: UUID,
    owner_id: UUID,
    targets: dict[str, ImportTarget],
    columns: dict[str, dict[str, ImportColumn]],
) -> tuple[SemanticModel, dict[str, SemanticModelSource]]:
    model = SemanticModel(
        workspace_id=workspace_id,
        name=f"M3 chart star {uuid4().hex}",
        version=1,
        status="active",
        created_by_user_id=owner_id,
    )
    session.add(model)
    session.flush()
    sources = {
        name: SemanticModelSource(
            semantic_model_id=model.id,
            target_id=targets[name].id,
            alias=name,
            source_role="fact" if name == "sales" else "dimension",
            ordinal=ordinal,
        )
        for ordinal, name in enumerate(("sales", "product", "region"))
    }
    session.add_all(sources.values())
    session.flush()
    joins = {
        name: SemanticModelJoin(
            semantic_model_id=model.id,
            left_source_id=sources["sales"].id,
            right_source_id=sources[name].id,
            join_type="left",
            cardinality="many_to_one",
            ordinal=ordinal,
        )
        for ordinal, name in enumerate(("product", "region"))
    }
    session.add_all(joins.values())
    session.flush()
    session.add_all(
        [
            SemanticModelJoinKey(
                semantic_model_join_id=joins[name].id,
                left_column_id=columns["sales"][f"{name}_key"].id,
                right_column_id=columns[name][f"{name}_key"].id,
                ordinal=0,
            )
            for name in ("product", "region")
        ]
    )
    return model, sources


def _add_dataset_resources(
    session: Session,
    workspace_id: UUID,
    owner_id: UUID,
    model: SemanticModel,
    sources: dict[str, SemanticModelSource],
    columns: dict[str, dict[str, ImportColumn]],
) -> tuple[Dataset, dict[str, DatasetField], Metric]:
    dataset = Dataset(
        workspace_id=workspace_id,
        semantic_model_id=model.id,
        name=f"M3 chart dataset {uuid4().hex}",
        version=1,
        status="active",
        created_by_user_id=owner_id,
    )
    session.add(dataset)
    session.flush()
    definitions = [
        ("sales", "sold_on", "Sold on", "dimension", "date"),
        ("sales", "occurred_at", "Occurred at", "dimension", "datetime"),
        ("sales", "product_key", "Product key", "dimension", "string"),
        ("sales", "region_key", "Region key", "dimension", "string"),
        ("sales", "is_returned", "Returned", "dimension", "boolean"),
        ("sales", "gross_amount", "Gross amount", "measure", "decimal"),
        ("sales", "quantity", "Quantity", "measure", "integer"),
        ("product", "product_name", "Product name", "dimension", "string"),
        ("product", "category", "Category", "dimension", "string"),
        ("region", "region_name", "Region name", "dimension", "string"),
    ]
    fields = {
        name: DatasetField(
            dataset_id=dataset.id,
            model_source_id=sources[source_name].id,
            source_column_id=columns[source_name][name].id,
            name=name,
            label=label,
            field_kind="source",
            field_role=role,
            data_type=data_type,
            ordinal=ordinal,
        )
        for ordinal, (source_name, name, label, role, data_type) in enumerate(definitions)
    }
    session.add_all(fields.values())
    session.flush()
    metric = Metric(
        workspace_id=workspace_id,
        dataset_id=dataset.id,
        code=f"gross_{uuid4().hex}",
        name="Gross revenue",
        version=1,
        description="Portable governed gross revenue",
        formula={
            "op": "aggregate",
            "function": "sum",
            "field_id": str(fields["gross_amount"].id),
        },
        result_type="decimal",
        unit="currency",
        status="active",
        owner_user_id=owner_id,
    )
    session.add(metric)
    session.flush()
    return dataset, fields, metric


def _add_dashboard_resources(
    session: Session,
    workspace_id: UUID,
    users: dict[str, User],
    dataset: Dataset,
    fields: dict[str, DatasetField],
    metric: Metric,
) -> tuple[Dashboard, DashboardVersion, DashboardPage, dict[str, UUID]]:
    dashboard = Dashboard(
        workspace_id=workspace_id,
        name=f"M3 chart dashboard {uuid4().hex}",
        status="active",
        owner_user_id=users["owner"].id,
    )
    session.add(dashboard)
    session.flush()
    version = DashboardVersion(
        dashboard_id=dashboard.id,
        version=1,
        status="active",
        global_filter=_date_filter(fields["sold_on"].id, "2026-01-01", "2026-02-01"),
        created_by_user_id=users["owner"].id,
    )
    session.add(version)
    session.flush()
    page = DashboardPage(
        dashboard_version_id=version.id,
        page_id=uuid4(),
        title="Overview",
        ordinal=0,
        page_filter=_logical_filter(
            _comparison_filter(fields["region_key"].id, "R-NORTH"),
            _date_filter(fields["sold_on"].id, "2026-01-01", "2026-03-01"),
        ),
    )
    session.add(page)
    session.flush()
    component_ids = {
        name: uuid4() for name in ("kpi", "bar", "line", "pie", "detail", "ranking", "stacked")
    }
    specs = {
        "kpi": (
            "kpi",
            _chart_config(
                dataset.id,
                measures=[_metric_measure(metric.id)],
                component_filter=_logical_filter(
                    _comparison_filter(fields["category"].id, "Hardware"),
                    _date_filter(fields["sold_on"].id, "2026-01-01", "2026-03-01"),
                ),
            ),
        ),
        "bar": (
            "bar",
            _chart_config(
                dataset.id,
                dimensions=[_dimension(fields["category"].id, "category")],
                measures=[_field_measure(fields["gross_amount"].id)],
            ),
        ),
        "line": (
            "line",
            _chart_config(
                dataset.id,
                dimensions=[_dimension(fields["sold_on"].id, "month", time_grain="month")],
                measures=[_field_measure(fields["gross_amount"].id)],
            ),
        ),
        "pie": (
            "pie",
            _chart_config(
                dataset.id,
                dimensions=[_dimension(fields["category"].id, "category")],
                measures=[_field_measure(fields["gross_amount"].id)],
            ),
        ),
        "detail": (
            "detail_table",
            _chart_config(
                dataset.id,
                dimensions=[
                    _dimension(fields["sold_on"].id, "sold_on"),
                    _dimension(fields["occurred_at"].id, "occurred_at"),
                    _dimension(fields["product_key"].id, "product_key"),
                    _dimension(fields["is_returned"].id, "is_returned"),
                ],
                measures=[_field_measure(fields["gross_amount"].id)],
            ),
        ),
        "ranking": (
            "ranking_table",
            _chart_config(
                dataset.id,
                dimensions=[_dimension(fields["product_key"].id, "product_key")],
                measures=[_field_measure(fields["gross_amount"].id)],
                sort=[
                    {
                        "kind": "field",
                        "field_id": str(fields["gross_amount"].id),
                        "aggregate": "sum",
                        "direction": "desc",
                    }
                ],
                top_n=2,
            ),
        ),
        "stacked": (
            "stacked_bar",
            _chart_config(
                dataset.id,
                dimensions=[_dimension(fields["category"].id, "category")],
                series_dimension={
                    "field_id": str(fields["region_name"].id),
                    "slot_key": "region",
                    "max_series": 5,
                },
                measures=[_field_measure(fields["gross_amount"].id)],
                query_limit=100,
            ),
        ),
    }
    for ordinal, (name, (component_type, config)) in enumerate(specs.items()):
        session.add(
            DashboardComponent(
                dashboard_version_id=version.id,
                component_id=component_ids[name],
                page_row_id=page.id,
                component_type=component_type,
                config_schema_version=1,
                config=config,
                ordinal=ordinal,
            )
        )
    layout_items = [
        {
            "component_id": str(component_id),
            "x": index % 4,
            "y": index // 4,
            "width": 1,
            "height": 1,
            "min_width": 1,
            "min_height": 1,
        }
        for index, component_id in enumerate(component_ids.values())
    ]
    session.add_all(
        [
            DashboardLayout(
                dashboard_version_id=version.id,
                profile=profile,
                columns=4 if profile == "desktop" else 1,
                row_height=80,
                items=layout_items,
            )
            for profile in ("desktop", "mobile")
        ]
    )
    session.add(
        DashboardPermission(
            dashboard_id=dashboard.id,
            subject_type="user",
            subject_id=users["viewer"].id,
            capability="view",
            created_by_user_id=users["owner"].id,
        )
    )
    return dashboard, version, page, component_ids


def _add_row_policies(
    session: Session,
    workspace_id: UUID,
    users: dict[str, User],
    dataset: Dataset,
    fields: dict[str, DatasetField],
) -> None:
    policies = [
        RowPolicy(
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            name="Owner all rows",
            version=1,
            effect="allow",
            expression={
                "kind": "comparison",
                "field_id": str(fields["gross_amount"].id),
                "operator": "gte",
                "value": 0,
            },
            status="active",
            created_by_user_id=users["owner"].id,
        ),
        RowPolicy(
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            name="Viewer north rows",
            version=1,
            effect="allow",
            expression=_comparison_filter(fields["region_key"].id, "R-NORTH"),
            status="active",
            created_by_user_id=users["owner"].id,
        ),
    ]
    session.add_all(policies)
    session.flush()
    session.add_all(
        [
            RowPolicyAssignment(row_policy_id=policies[0].id, user_id=users["owner"].id),
            RowPolicyAssignment(row_policy_id=policies[1].id, user_id=users["viewer"].id),
        ]
    )


def _chart_config(
    dataset_id: UUID,
    *,
    dimensions: list[dict[str, object]] | None = None,
    measures: list[dict[str, object]],
    series_dimension: dict[str, object] | None = None,
    sort: list[dict[str, object]] | None = None,
    top_n: int | None = None,
    query_limit: int = 500,
    component_filter: dict[str, object] | None = None,
) -> dict[str, object]:
    query: dict[str, object] = {
        "dataset_id": str(dataset_id),
        "dimensions": [] if dimensions is None else dimensions,
        "measures": measures,
        "sort": [] if sort is None else sort,
        "query_limit": query_limit,
    }
    if series_dimension is not None:
        query["series_dimension"] = series_dimension
    if top_n is not None:
        query["top_n"] = top_n
    return {
        "schema_version": 1,
        "title": "Portable chart",
        "description": None,
        "query": query,
        "component_filter": component_filter,
        "presentation": {},
    }


def _dimension(
    field_id: UUID, slot_key: str, *, time_grain: str | None = None
) -> dict[str, object]:
    result: dict[str, object] = {"field_id": str(field_id), "slot_key": slot_key}
    if time_grain is not None:
        result["time_grain"] = time_grain
    return result


def _field_measure(field_id: UUID) -> dict[str, object]:
    return {
        "kind": "field",
        "field_id": str(field_id),
        "aggregate": "sum",
        "slot_key": "gross",
    }


def _metric_measure(metric_id: UUID) -> dict[str, object]:
    return {"kind": "metric", "metric_version_id": str(metric_id), "slot_key": "gross"}


def _comparison_filter(field_id: UUID, value: str) -> dict[str, object]:
    return {"kind": "comparison", "field_id": str(field_id), "operator": "eq", "value": value}


def _date_filter(field_id: UUID, start: str, end: str) -> dict[str, object]:
    return {
        "kind": "absolute_date_range",
        "field_id": str(field_id),
        "field_type": "date",
        "start": start,
        "end": end,
    }


def _logical_filter(*predicates: dict[str, object]) -> dict[str, object]:
    return {"kind": "logical", "operator": "and", "predicates": list(predicates)}
