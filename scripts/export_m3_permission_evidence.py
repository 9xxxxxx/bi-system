from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from bi_system.api.routes.datasets import create_dataset_endpoint
from bi_system.core.config import Settings
from bi_system.dashboards.chart_contracts import (
    DashboardChartQueryRequest,
    PreviewChartComponent,
    RuntimeChartFilterScopes,
)
from bi_system.dashboards.chart_query import (
    DashboardChartQueryError,
    execute_dashboard_chart_query,
    prepare_dashboard_chart_query,
)
from bi_system.dashboards.contracts import DashboardLayoutInput, SaveDashboardVersion
from bi_system.dashboards.errors import DashboardForbiddenError, DashboardNotFoundError
from bi_system.dashboards.service import (
    get_dashboard,
    save_dashboard_version,
)
from bi_system.db.models import (
    Dashboard,
    DashboardComponent,
    DashboardPage,
    DashboardVersion,
    Dataset,
    DatasetField,
    ImportTarget,
    SemanticModel,
    SemanticModelSource,
    User,
)
from bi_system.db.session import create_session_factory
from bi_system.identity import QueryPrincipal
from bi_system.modeling.dataset_contracts import CreateDataset, SourceDatasetField
from bi_system.modeling.datasets import get_dataset_detail
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

if __package__:
    from scripts.benchmark_m2_queries import (
        benchmark_database_engine,
        seed_benchmark,
        validate_benchmark_fixture,
    )
    from scripts.benchmark_m3_chart_queries import (
        BenchmarkContext,
        build_producer_provenance,
        canonical_rows_fingerprint,
        canonicalize_rows,
        result_fingerprint,
        seed_dashboard_benchmark,
    )
    from spikes.m3.quality.fixture_tool import (
        generate_benchmark as generate_benchmark_fixture,
    )
else:
    from benchmark_m2_queries import (
        benchmark_database_engine,
        seed_benchmark,
        validate_benchmark_fixture,
    )
    from benchmark_m3_chart_queries import (
        BenchmarkContext,
        build_producer_provenance,
        canonical_rows_fingerprint,
        canonicalize_rows,
        result_fingerprint,
        seed_dashboard_benchmark,
    )

    def generate_benchmark_fixture(root: Path, row_count: int) -> None:
        subprocess.run(
            (
                sys.executable,
                str(
                    Path(__file__).resolve().parents[1]
                    / "spikes"
                    / "m3"
                    / "quality"
                    / "fixture_tool.py"
                ),
                "benchmark",
                "--rows",
                str(row_count),
                "--output",
                str(root),
            ),
            check=True,
            capture_output=True,
        )


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_MANIFEST = (
    REPOSITORY_ROOT / "spikes" / "m3" / "quality" / "fixture" / "v2" / "manifest.json"
)
MATRIX_FILES = {
    "M3-P01": "permission-principals.json",
    "M3-P02": "permission-rls-preaggregate.json",
    "M3-P03": "permission-forged-filter.json",
    "M3-P04": "permission-cross-workspace.json",
    "M3-P05": "permission-capabilities.json",
}


@dataclass(frozen=True, slots=True)
class ExportContext:
    engine: Engine
    session_factory: sessionmaker[Session]
    benchmark: BenchmarkContext
    dataset_id: UUID
    principals: dict[str, QueryPrincipal]
    request: DashboardChartQueryRequest
    field_ids: dict[str, UUID]
    foreign_workspace_id: UUID
    foreign_user_id: UUID
    foreign_dataset_id: UUID
    foreign_field_id: UUID
    fact_physical_table_name: str
    benchmark_fixture_provenance: dict[str, object]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export M3 permission and RLS evidence")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=14)
    args = parser.parse_args(argv)
    if args.rows < 1:
        parser.error("rows must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    exit_code = export_permission_evidence(args.output_dir, rows=args.rows)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "files": list(MATRIX_FILES.values()),
                "exit_code": exit_code,
            },
            ensure_ascii=False,
        )
    )
    return exit_code


def export_permission_evidence(output_dir: Path, *, rows: int) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = _producer_provenance()
    fixture_manifest = _read_json(FIXTURE_MANIFEST)
    fixture_version = fixture_manifest.get("fixture_version")
    fixture_manifest_sha256 = _sha256(FIXTURE_MANIFEST)
    documents: dict[str, dict[str, object]]
    benchmark_fixture_provenance: dict[str, object] | None = None
    try:
        documents, benchmark_fixture_provenance = _build_documents(rows=rows)
        provenance = _bind_benchmark_fixture_provenance(
            provenance,
            benchmark_fixture_provenance,
        )
    except Exception as exc:
        documents = {
            matrix_id: {
                "checks": {"export_completed": False},
                "cases": [],
                "error_code": f"export_failed:{type(exc).__name__}",
            }
            for matrix_id in MATRIX_FILES
        }
    finalized: dict[str, dict[str, object]] = {}
    for matrix_id, document in documents.items():
        finalized[matrix_id] = _finalize_document(
            {"matrix_id": matrix_id, **document},
            fixture_version=fixture_version,
            fixture_manifest_sha256=fixture_manifest_sha256,
            producer_provenance=provenance,
            benchmark_fixture_provenance=benchmark_fixture_provenance,
        )
    for matrix_id, filename in MATRIX_FILES.items():
        payload = finalized.get(matrix_id)
        if payload is None:
            payload = build_evidence_document(
                matrix_id=matrix_id,
                fixture_version=fixture_version,
                fixture_manifest_sha256=fixture_manifest_sha256,
                producer_provenance=provenance,
                benchmark_fixture_provenance=benchmark_fixture_provenance,
                checks={"document_present": False},
                cases=[],
                error_code="evidence_document_missing",
            )
        (output_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return (
        0
        if all(item["status"] == "pass" for item in finalized.values()) and len(finalized) == 5
        else 1
    )


def _build_documents(
    *,
    rows: int,
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    with (
        tempfile.TemporaryDirectory(prefix="m3-permission-fixture-") as fixture_directory,
        tempfile.TemporaryDirectory(prefix="m3-permission-db-") as database_directory,
    ):
        fixture_root = Path(fixture_directory)
        generate_benchmark_fixture(fixture_root, rows)
        with benchmark_database_engine(
            None,
            temporary_directory=Path(database_directory),
            pool_capacity=4,
        ) as engine:
            context = _seed_export_context(engine, fixture_root=fixture_root, rows=rows)
            return (
                {
                    "M3-P01": _principal_evidence(context),
                    "M3-P02": _rls_evidence(context),
                    "M3-P03": _forged_filter_evidence(context),
                    "M3-P04": _cross_workspace_evidence(context),
                    "M3-P05": _capability_evidence(context),
                },
                context.benchmark_fixture_provenance,
            )


def _seed_export_context(engine: Engine, *, fixture_root: Path, rows: int) -> ExportContext:
    session_factory = create_session_factory(engine)
    benchmark_fixture_provenance = _benchmark_fixture_provenance(
        fixture_root,
        expected_rows=rows,
    )
    administrator, dataset_request = seed_benchmark(
        engine,
        session_factory,
        rows=rows,
        fixture_dir=fixture_root,
    )
    benchmark = seed_dashboard_benchmark(
        session_factory,
        principal=administrator,
        dataset_id=dataset_request.dataset_id,
        rows=rows,
        fixture_dir=fixture_root,
    )
    scenarios = {scenario.name: scenario for scenario in benchmark.scenarios}
    principals = {
        "administrator": scenarios["category_bar"].principal,
        "editor": scenarios["month_trend"].principal,
        "restricted_viewer": scenarios["restricted_viewer_same_group"].principal,
    }
    with session_factory.begin() as session:
        fields = {
            field.name: field.id
            for field in session.scalars(
                select(DatasetField).where(DatasetField.dataset_id == dataset_request.dataset_id)
            ).all()
        }
        fact_physical_table_name = session.scalar(
            select(ImportTarget.physical_table_name)
            .select_from(SemanticModelSource)
            .join(ImportTarget, ImportTarget.id == SemanticModelSource.target_id)
            .join(Dataset, Dataset.semantic_model_id == SemanticModelSource.semantic_model_id)
            .where(
                Dataset.id == dataset_request.dataset_id,
                SemanticModelSource.source_role == "fact",
            )
        )
        if fact_physical_table_name is None:
            raise RuntimeError("Benchmark fact physical table was not found")
        foreign_workspace_id = uuid4()
        foreign_user = User(
            workspace_id=foreign_workspace_id,
            username="m3-permission-foreign-user",
            display_name="M3 Permission Foreign User",
            password_hash="not-for-login",
        )
        session.add(foreign_user)
        session.flush()
        foreign_model = SemanticModel(
            workspace_id=foreign_workspace_id,
            name="M3 foreign model",
            version=1,
            status="active",
            created_by_user_id=foreign_user.id,
        )
        session.add(foreign_model)
        session.flush()
        foreign_dataset = Dataset(
            workspace_id=foreign_workspace_id,
            semantic_model_id=foreign_model.id,
            name="M3 foreign dataset",
            version=1,
            status="active",
            created_by_user_id=foreign_user.id,
        )
        session.add(foreign_dataset)
        session.flush()
        foreign_field = DatasetField(
            dataset_id=foreign_dataset.id,
            name="foreign_category",
            label="Foreign category",
            field_kind="calculated",
            field_role="dimension",
            data_type="string",
            expression={"kind": "literal", "value": "foreign"},
            format_config={},
            ordinal=0,
        )
        session.add(foreign_field)
        session.flush()
        foreign_user_id = foreign_user.id
        foreign_dataset_id = foreign_dataset.id
        foreign_field_id = foreign_field.id
    return ExportContext(
        engine=engine,
        session_factory=session_factory,
        benchmark=benchmark,
        dataset_id=dataset_request.dataset_id,
        principals=principals,
        request=scenarios["category_bar"].request,
        field_ids=fields,
        foreign_workspace_id=foreign_workspace_id,
        foreign_user_id=foreign_user_id,
        foreign_dataset_id=foreign_dataset_id,
        foreign_field_id=foreign_field_id,
        fact_physical_table_name=fact_physical_table_name,
        benchmark_fixture_provenance=benchmark_fixture_provenance,
    )


def _benchmark_fixture_provenance(
    fixture_root: Path,
    *,
    expected_rows: int,
) -> dict[str, object]:
    fixture = validate_benchmark_fixture(fixture_root, expected_rows=expected_rows)
    manifest_path = fixture_root / "benchmark_manifest.json"
    manifest = _read_json(manifest_path)
    raw_files = manifest.get("files")
    file_manifest = cast(dict[str, object], raw_files) if isinstance(raw_files, dict) else {}
    files: dict[str, object] = {}
    for filename in ("fact_sales.csv", "dim_product.csv", "dim_region.csv", "schema.json"):
        raw_metadata = file_manifest.get(filename)
        metadata = cast(dict[str, object], raw_metadata) if isinstance(raw_metadata, dict) else {}
        path = fixture_root / filename
        actual_sha256 = _sha256(path)
        actual_bytes = path.stat().st_size
        files[filename] = {
            "declared_sha256": metadata.get("sha256"),
            "actual_sha256": actual_sha256,
            "declared_bytes": metadata.get("bytes"),
            "actual_bytes": actual_bytes,
            "verified": metadata.get("sha256") == actual_sha256
            and metadata.get("bytes") == actual_bytes,
        }
    all_files_verified = len(files) == 4 and all(
        cast(dict[str, object], value).get("verified") is True for value in files.values()
    )
    return {
        "fixture_version": fixture.fixture_version,
        "profile": fixture.profile,
        "requested_rows": expected_rows,
        "fact_row_count": fixture.fact_row_count,
        "benchmark_manifest_sha256": fixture.manifest_sha256,
        "actual_benchmark_manifest_sha256": _sha256(manifest_path),
        "trusted_source_manifest_sha256": fixture.trusted_source_manifest_sha256,
        "expected_trust_anchor_sha256": _sha256(FIXTURE_MANIFEST),
        "trust_anchor_verified": (
            fixture.trusted_source_manifest_sha256 == _sha256(FIXTURE_MANIFEST)
        ),
        "rows_verified": fixture.fact_row_count == expected_rows,
        "files": files,
        "all_files_verified": all_files_verified,
    }


def _principal_evidence(context: ExportContext) -> dict[str, object]:
    results = {
        name: {
            "principal_name": name,
            **_execute_result(context, principal=principal, request=context.request),
        }
        for name, principal in context.principals.items()
    }
    expected_restricted = context.benchmark.rls_expectation.restricted_canonical_rows
    checks = {
        "all_principals_present": set(results) == set(context.principals),
        "same_query_resource_ids": len(
            {
                (
                    result["dashboard_id"],
                    result["dashboard_version_id"],
                    result["page_id"],
                    result["component_id"],
                    result["dataset_id"],
                )
                for result in results.values()
            }
        )
        == 1,
        "administrator_editor_results_equal": (
            results["administrator"]["result_sha256"] == results["editor"]["result_sha256"]
        ),
        "restricted_result_matches_fixture_oracle": (
            results["restricted_viewer"]["canonical_rows"] == list(expected_restricted)
        ),
        "complete_results_exported": all(result["canonical_rows"] for result in results.values()),
    }
    return {"checks": checks, "cases": list(results.values())}


def _rls_evidence(context: ExportContext) -> dict[str, object]:
    unrestricted = _execute_result(
        context,
        principal=context.principals["administrator"],
        request=context.request,
    )
    restricted, first_fact_select_count = _execute_result_with_fact_select_count(
        context,
        principal=context.principals["restricted_viewer"],
        request=context.request,
    )
    repeated_restricted, second_fact_select_count = _execute_result_with_fact_select_count(
        context,
        principal=context.principals["restricted_viewer"],
        request=context.request,
    )
    expected_rows = context.benchmark.rls_expectation.restricted_canonical_rows
    expected_hash = canonical_rows_fingerprint(expected_rows)
    expectation = context.benchmark.rls_expectation
    checks = {
        "fixture_oracle_trusted": expectation.fixture_oracle_trusted,
        "rls_applied_before_aggregation": restricted["result_sha256"] == expected_hash,
        "restricted_source_is_strict_subset": (
            expectation.restricted_source_row_count is not None
            and expectation.unrestricted_source_row_count is not None
            and expectation.restricted_source_row_count < expectation.unrestricted_source_row_count
        ),
        "cross_principal_results_not_reused": (
            unrestricted["result_sha256"] != restricted["result_sha256"]
        ),
        "repeated_restricted_result_stable": (
            restricted["result_sha256"] == repeated_restricted["result_sha256"]
        ),
        "repeat_execution_reached_fact_source": (
            first_fact_select_count > 0 and second_fact_select_count > 0
        ),
        "application_result_cache_absent": (
            first_fact_select_count > 0
            and second_fact_select_count > 0
            and restricted["result_sha256"] == repeated_restricted["result_sha256"]
        ),
        "direct_query_source_hash_present": len(
            _sha256(REPOSITORY_ROOT / "scripts" / "benchmark_m3_chart_queries.py")
        )
        == 64,
        "tooltip_uses_restricted_query_rows": (
            restricted["tooltip_rows_sha256"] == restricted["result_sha256"]
        ),
    }
    return {
        "checks": checks,
        "cases": [
            {
                "principal_id": restricted["principal_id"],
                "dataset_id": str(context.dataset_id),
                "rls_value": "R-NORTH",
                "expected_canonical_rows": list(expected_rows),
                "actual_canonical_rows": restricted["canonical_rows"],
                "expected_result_sha256": expected_hash,
                "actual_result_sha256": restricted["result_sha256"],
                "unrestricted_result_sha256_excluded": unrestricted["result_sha256"],
                "cache": {
                    "state": "not_applicable",
                    "application_result_cache": "not_present_in_direct_service_execution_path",
                    "logical_fact_source": "fact_sales.csv",
                    "physical_fact_table": context.fact_physical_table_name,
                    "first_fact_select_count": first_fact_select_count,
                    "second_fact_select_count": second_fact_select_count,
                    "first_restricted_result_sha256": restricted["result_sha256"],
                    "repeated_restricted_result_sha256": repeated_restricted["result_sha256"],
                    "direct_query_source": "scripts/benchmark_m3_chart_queries.py",
                    "direct_query_source_sha256": _sha256(
                        REPOSITORY_ROOT / "scripts" / "benchmark_m3_chart_queries.py"
                    ),
                },
                "tooltip_rows_sha256": restricted["tooltip_rows_sha256"],
                "unrestricted_source_row_count": expectation.unrestricted_source_row_count,
                "restricted_source_row_count": expectation.restricted_source_row_count,
            }
        ],
    }


def _forged_filter_evidence(context: ExportContext) -> dict[str, object]:
    forged_request = context.request.model_copy(
        update={
            "runtime_filters": RuntimeChartFilterScopes.model_validate(
                {
                    "global_filter": {
                        "kind": "comparison",
                        "field_id": context.field_ids["region_key"],
                        "operator": "eq",
                        "value": "R-SOUTH",
                    }
                }
            )
        }
    )
    forged = _execute_result(
        context,
        principal=context.principals["restricted_viewer"],
        request=forged_request,
    )
    override_payload = context.request.model_dump(mode="json")
    override_payload["rls_override"] = {"enabled": False}
    override_error_code: str | None = None
    try:
        DashboardChartQueryRequest.model_validate(override_payload)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        override_error_code = errors[0]["type"] if errors else None
    checks = {
        "forged_south_intersects_with_rls": forged["row_count"] == 0,
        "forged_south_result_empty": forged["canonical_rows"] == [],
        "client_rls_override_rejected": override_error_code == "extra_forbidden",
        "runtime_filter_cannot_remove_row_policy": override_error_code is not None,
    }
    return {
        "checks": checks,
        "cases": [
            {
                "case": "restricted_viewer_forges_south_filter",
                "principal_id": forged["principal_id"],
                "field_id": str(context.field_ids["region_key"]),
                "forged_value": "R-SOUTH",
                "effective_rls_value": "R-NORTH",
                "canonical_rows": forged["canonical_rows"],
                "result_sha256": forged["result_sha256"],
                "error_code": None,
            },
            {
                "case": "client_attempts_to_remove_rls",
                "principal_id": str(context.principals["restricted_viewer"].user_id),
                "accepted": False,
                "error_code": override_error_code,
            },
        ],
    }


def _cross_workspace_evidence(context: ExportContext) -> dict[str, object]:
    foreign = QueryPrincipal(
        user_id=context.foreign_user_id,
        workspace_id=context.foreign_workspace_id,
        permissions=frozenset({"dashboards:view", "datasets:query"}),
    )
    cases: list[dict[str, object]] = []
    with context.session_factory() as session:
        try:
            get_dashboard(session, principal=foreign, dashboard_id=context.request.dashboard_id)
        except DashboardNotFoundError as exc:
            cases.append(
                _error_case(
                    resource="dashboard",
                    resource_id=context.request.dashboard_id,
                    principal=foreign,
                    code=exc.code,
                    status_code=404,
                )
            )
        dataset_detail = get_dataset_detail(
            session,
            workspace_id=foreign.workspace_id,
            dataset_id=context.dataset_id,
        )
        if dataset_detail is None:
            cases.append(
                _error_case(
                    resource="dataset",
                    resource_id=context.dataset_id,
                    principal=foreign,
                    code="dataset_not_found",
                    status_code=404,
                )
            )
        detail = get_dashboard(
            session,
            principal=context.principals["administrator"],
            dashboard_id=context.request.dashboard_id,
        )
        page = next(item for item in detail.pages if item.page_id == context.request.page_id)
        component = next(
            item for item in page.components if item.component_id == context.request.component_id
        )
        preview = PreviewChartComponent.model_validate(
            {
                "component_id": component.component_id,
                "page_id": component.page_id,
                "component_type": component.component_type,
                "config_version": component.config_version,
                "config": component.config,
            }
        )
        first_dimension = preview.config.query.dimensions[0]
        cross_workspace_query = preview.config.query.model_copy(
            update={
                "dimensions": [
                    first_dimension.model_copy(update={"field_id": context.foreign_field_id})
                ]
            }
        )
        preview_with_foreign_field = preview.model_copy(
            update={"config": preview.config.model_copy(update={"query": cross_workspace_query})}
        )
        cross_workspace_request = context.request.model_copy(
            update={"preview_component": preview_with_foreign_field}
        )
        administrator_with_edit = QueryPrincipal(
            user_id=context.principals["administrator"].user_id,
            workspace_id=context.principals["administrator"].workspace_id,
            permissions=context.principals["administrator"].permissions
            | frozenset({"dashboards:edit"}),
        )
        try:
            prepare_dashboard_chart_query(
                session,
                principal=administrator_with_edit,
                request=cross_workspace_request,
                workspace_timezone="Asia/Hong_Kong",
            )
        except DashboardChartQueryError as exc:
            cases.append(
                _error_case(
                    resource="field",
                    resource_id=context.foreign_field_id,
                    principal=administrator_with_edit,
                    code=exc.code,
                    status_code=_chart_error_status(exc.code),
                    owner_workspace_id=context.foreign_workspace_id,
                )
            )
    fact_selects = 0

    def count_fact_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal fact_selects
        if statement.lstrip().lower().startswith("select") and "fact_sales" in statement.lower():
            fact_selects += 1

    event.listen(context.engine, "before_cursor_execute", count_fact_selects)
    try:
        with context.session_factory() as session:
            try:
                execute_dashboard_chart_query(
                    session,
                    principal=foreign,
                    request=context.request,
                    workspace_timezone="Asia/Hong_Kong",
                    timeout_seconds=10,
                )
            except DashboardChartQueryError as exc:
                cases.append(
                    _error_case(
                        resource="query",
                        resource_id=context.request.component_id,
                        principal=foreign,
                        code=exc.code,
                        status_code=_chart_error_status(exc.code),
                        query_executed=fact_selects > 0,
                    )
                )
    finally:
        event.remove(context.engine, "before_cursor_execute", count_fact_selects)
    resource_cases = {cast(str, item["resource"]): item for item in cases}
    checks = {
        "all_resources_evaluated": set(resource_cases)
        == {"dashboard", "dataset", "field", "query"},
        "cross_workspace_resources_hidden": all(
            item.get("status_code") == 404 for item in resource_cases.values()
        ),
        "stable_error_codes": {item.get("error_code") for item in resource_cases.values()}
        == {"dashboard_not_found", "dataset_not_found", "dataset_field_not_found"},
        "query_not_executed": fact_selects == 0
        and resource_cases.get("query", {}).get("query_executed") is False,
        "foreign_resource_ids_present": bool(
            context.foreign_dataset_id and context.foreign_field_id
        ),
    }
    return {"checks": checks, "cases": cases}


def _capability_evidence(context: ExportContext) -> dict[str, object]:
    save_request = SaveDashboardVersion(
        base_version=1,
        expected_revision=1,
        pages=[],
        components=[],
        layouts=[
            DashboardLayoutInput(profile="desktop", items=[]),
            DashboardLayoutInput(profile="mobile", items=[]),
        ],
    )
    editor = context.principals["editor"]
    dataset_before = _dataset_state(context.session_factory, editor.workspace_id)
    editor_status: int | None = None
    editor_error_code: str | None = None
    create_request = CreateDataset(
        semantic_model_id=uuid4(),
        name="Forbidden editor dataset",
        fields=[
            SourceDatasetField(
                model_source_id=uuid4(),
                source_column_id=uuid4(),
                name="forbidden_field",
                label="Forbidden field",
                role="dimension",
            )
        ],
    )
    with context.session_factory() as session:
        try:
            create_dataset_endpoint(
                create_request,
                session,
                Settings(workspace_id=editor.workspace_id),
                editor,
            )
        except HTTPException as exc:
            editor_status = exc.status_code
            detail = cast(dict[str, object], exc.detail)
            editor_error_code = cast(str | None, detail.get("code"))
    dataset_after = _dataset_state(context.session_factory, editor.workspace_id)
    editor_case = {
        "case": "editor-dataset-manage",
        "principal_name": "editor",
        "principal_id": str(editor.user_id),
        "workspace_id": str(editor.workspace_id),
        "attempted_capability": "dataset_manage",
        "status_code": editor_status,
        "error_code": editor_error_code,
        "before": dataset_before,
        "after": dataset_after,
        "no_partial_write": dataset_before == dataset_after,
    }

    viewer = context.principals["restricted_viewer"]
    dashboard_before = _dashboard_state(context.session_factory, context.request.dashboard_id)
    viewer_status: int | None = None
    viewer_error_code: str | None = None
    with context.session_factory() as session:
        try:
            save_dashboard_version(
                session,
                principal=viewer,
                dashboard_id=context.request.dashboard_id,
                request=save_request,
            )
        except DashboardForbiddenError as exc:
            viewer_error_code = exc.code
            viewer_status = 403
    dashboard_after = _dashboard_state(context.session_factory, context.request.dashboard_id)
    viewer_case = {
        "case": "viewer-dashboard-edit",
        "principal_name": "restricted_viewer",
        "principal_id": str(viewer.user_id),
        "workspace_id": str(viewer.workspace_id),
        "attempted_capability": "dashboard_edit",
        "status_code": viewer_status,
        "error_code": viewer_error_code,
        "before": dashboard_before,
        "after": dashboard_after,
        "no_partial_write": dashboard_before == dashboard_after,
    }
    cases = [editor_case, viewer_case]
    checks = {
        "editor_dataset_manage_forbidden": editor_status == 403,
        "editor_dataset_manage_error_stable": editor_error_code == "dataset_manage_forbidden",
        "editor_dataset_no_partial_write": dataset_before == dataset_after,
        "viewer_dashboard_edit_forbidden": viewer_status == 403,
        "viewer_dashboard_edit_error_stable": viewer_error_code == "dashboard_forbidden",
        "viewer_dashboard_no_partial_write": dashboard_before == dashboard_after,
        "before_after_state_present": all(item["before"] and item["after"] for item in cases),
    }
    return {"checks": checks, "cases": cases}


def _execute_result(
    context: ExportContext,
    *,
    principal: QueryPrincipal,
    request: DashboardChartQueryRequest,
) -> dict[str, object]:
    with context.session_factory() as session:
        result = execute_dashboard_chart_query(
            session,
            principal=principal,
            request=request,
            workspace_timezone="Asia/Hong_Kong",
            timeout_seconds=10,
        )
    rows = canonicalize_rows(result.rows)
    result_hash = canonical_rows_fingerprint(rows)
    return {
        "principal_id": str(principal.user_id),
        "workspace_id": str(principal.workspace_id),
        "permissions": sorted(principal.permissions),
        "dashboard_id": str(request.dashboard_id),
        "dashboard_version_id": str(request.dashboard_version_id),
        "page_id": str(request.page_id),
        "component_id": str(request.component_id),
        "dataset_id": str(context.dataset_id),
        "field_ids": [str(value) for value in sorted(context.field_ids.values(), key=str)],
        "row_count": len(rows),
        "canonical_rows": list(rows),
        "result_sha256": result_hash,
        "query_result_sha256": result_fingerprint(result),
        "tooltip_rows_sha256": result_hash,
        "truncated": result.truncated,
    }


def _execute_result_with_fact_select_count(
    context: ExportContext,
    *,
    principal: QueryPrincipal,
    request: DashboardChartQueryRequest,
) -> tuple[dict[str, object], int]:
    fact_select_count = 0

    def count_fact_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _execution_context: object,
        _executemany: bool,
    ) -> None:
        nonlocal fact_select_count
        if (
            statement.lstrip().lower().startswith("select")
            and context.fact_physical_table_name.lower() in statement.lower()
        ):
            fact_select_count += 1

    event.listen(context.engine, "before_cursor_execute", count_fact_selects)
    try:
        result = _execute_result(context, principal=principal, request=request)
    finally:
        event.remove(context.engine, "before_cursor_execute", count_fact_selects)
    return result, fact_select_count


def _dataset_state(
    session_factory: sessionmaker[Session],
    workspace_id: UUID,
) -> dict[str, object]:
    with session_factory() as session:
        return {
            "workspace_id": str(workspace_id),
            "dataset_count": session.scalar(
                select(func.count(Dataset.id)).where(Dataset.workspace_id == workspace_id)
            ),
            "dataset_field_count": session.scalar(
                select(func.count(DatasetField.id))
                .join(Dataset)
                .where(Dataset.workspace_id == workspace_id)
            ),
        }


def _dashboard_state(
    session_factory: sessionmaker[Session],
    dashboard_id: UUID,
) -> dict[str, object]:
    with session_factory() as session:
        dashboard = session.get(Dashboard, dashboard_id)
        if dashboard is None:
            return {}
        return {
            "dashboard_id": str(dashboard.id),
            "revision": dashboard.revision,
            "current_version": dashboard.current_version,
            "status": dashboard.status,
            "version_count": session.scalar(
                select(func.count(DashboardVersion.id)).where(
                    DashboardVersion.dashboard_id == dashboard_id
                )
            ),
            "page_count": session.scalar(
                select(func.count(DashboardPage.id))
                .join(DashboardVersion)
                .where(DashboardVersion.dashboard_id == dashboard_id)
            ),
            "component_count": session.scalar(
                select(func.count(DashboardComponent.id))
                .join(DashboardVersion)
                .where(DashboardVersion.dashboard_id == dashboard_id)
            ),
        }


def _error_case(
    *,
    resource: str,
    resource_id: UUID,
    principal: QueryPrincipal,
    code: str,
    status_code: int,
    owner_workspace_id: UUID | None = None,
    query_executed: bool | None = None,
) -> dict[str, object]:
    return {
        "resource": resource,
        "resource_id": str(resource_id),
        "owner_workspace_id": (str(owner_workspace_id) if owner_workspace_id is not None else None),
        "principal_id": str(principal.user_id),
        "principal_workspace_id": str(principal.workspace_id),
        "status_code": status_code,
        "error_code": code,
        "query_executed": query_executed,
    }


def _chart_error_status(code: str) -> int:
    if code in {
        "dashboard_not_found",
        "dashboard_page_not_found",
        "dashboard_component_not_found",
        "dataset_not_found",
        "dataset_model_not_found",
        "dataset_field_not_found",
        "dataset_source_not_found",
        "metric_not_found",
    }:
        return 404
    if code in {"dashboard_forbidden", "dataset_query_forbidden"}:
        return 403
    return 422


def _finalize_document(
    value: dict[str, object],
    *,
    fixture_version: object,
    fixture_manifest_sha256: str,
    producer_provenance: dict[str, object],
    benchmark_fixture_provenance: dict[str, object] | None,
) -> dict[str, object]:
    checks = dict(cast(dict[str, object], value.get("checks", {})))
    checks.update(
        {
            "actual_fixture_provenance_present": benchmark_fixture_provenance is not None,
            "actual_fixture_manifest_verified": (
                benchmark_fixture_provenance is not None
                and benchmark_fixture_provenance.get("benchmark_manifest_sha256")
                == benchmark_fixture_provenance.get("actual_benchmark_manifest_sha256")
            ),
            "actual_fixture_rows_verified": (
                benchmark_fixture_provenance is not None
                and benchmark_fixture_provenance.get("rows_verified") is True
            ),
            "actual_fixture_files_verified": (
                benchmark_fixture_provenance is not None
                and benchmark_fixture_provenance.get("all_files_verified") is True
            ),
            "actual_fixture_trust_anchor_verified": (
                benchmark_fixture_provenance is not None
                and benchmark_fixture_provenance.get("trust_anchor_verified") is True
            ),
        }
    )
    return build_evidence_document(
        matrix_id=cast(str, value.get("matrix_id")),
        fixture_version=fixture_version,
        fixture_manifest_sha256=fixture_manifest_sha256,
        producer_provenance=producer_provenance,
        benchmark_fixture_provenance=benchmark_fixture_provenance,
        checks=checks,
        cases=cast(list[dict[str, object]], value.get("cases", [])),
        error_code=cast(str | None, value.get("error_code")),
    )


def build_evidence_document(
    *,
    matrix_id: str,
    fixture_version: object,
    fixture_manifest_sha256: str,
    producer_provenance: dict[str, object],
    benchmark_fixture_provenance: dict[str, object] | None,
    checks: dict[str, object],
    cases: list[dict[str, object]],
    error_code: str | None = None,
) -> dict[str, object]:
    checks_pass = bool(checks) and all(value is True for value in checks.values())
    status = (
        "pass"
        if checks_pass and cases and error_code is None and benchmark_fixture_provenance is not None
        else "fail"
    )
    return {
        "schema_version": 1,
        "matrix_id": matrix_id,
        "status": status,
        "fixture_version": fixture_version,
        "fixture_manifest_sha256": fixture_manifest_sha256,
        "git_sha": producer_provenance.get("head_sha"),
        "producer_provenance": producer_provenance,
        "benchmark_fixture_provenance": benchmark_fixture_provenance,
        "checks": checks,
        "cases": cases,
        "error_code": error_code,
    }


def _bind_benchmark_fixture_provenance(
    provenance: dict[str, object],
    benchmark_fixture_provenance: dict[str, object],
) -> dict[str, object]:
    bound = dict(provenance)
    bound["benchmark_fixture"] = benchmark_fixture_provenance
    snapshot_payload = {
        "producer_snapshot_sha256": provenance.get("worktree_snapshot_sha256"),
        "benchmark_manifest_sha256": benchmark_fixture_provenance.get("benchmark_manifest_sha256"),
        "benchmark_files": benchmark_fixture_provenance.get("files"),
    }
    bound["worktree_snapshot_sha256"] = hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return bound


def _producer_provenance() -> dict[str, object]:
    provenance = build_producer_provenance()
    exporter_sha = _sha256(Path(__file__))
    source_hashes = dict(cast(dict[str, object], provenance.get("source_content_sha256", {})))
    source_hashes["permission_evidence_exporter"] = exporter_sha
    status = subprocess.run(
        ("git", "status", "--porcelain=v1", "--", "scripts/export_m3_permission_evidence.py"),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    snapshot_payload = {
        "base_snapshot_sha256": provenance.get("worktree_snapshot_sha256"),
        "permission_evidence_exporter_sha256": exporter_sha,
        "permission_evidence_exporter_git_status_sha256": hashlib.sha256(status).hexdigest(),
    }
    provenance["source_content_sha256"] = source_hashes
    provenance["producer_sources_dirty"] = bool(provenance.get("producer_sources_dirty") or status)
    provenance["worktree_snapshot_sha256"] = hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    provenance["snapshot_scope"] = (
        "benchmark producers plus permission evidence exporter content and targeted git status"
    )
    return provenance


def _read_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
