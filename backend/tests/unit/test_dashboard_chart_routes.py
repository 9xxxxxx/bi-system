# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
from collections.abc import Generator
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.api.dependencies import get_database_session, get_query_principal
from bi_system.api.routes import dashboard_chart_queries as routes
from bi_system.api.routes.dashboard_chart_queries import router
from bi_system.core.config import Settings, get_settings
from bi_system.dashboards.chart_query import (
    ChartColumn,
    DashboardChartQueryError,
    DashboardChartValidation,
)
from bi_system.identity import QueryPrincipal
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        ("dashboard_not_found", 404),
        ("dataset_query_forbidden", 403),
        ("dashboard_revision_conflict", 409),
        ("chart_slot_invalid", 422),
        ("series_result_truncated", 422),
        ("dataset_query_timeout", 504),
    ],
)
def test_chart_query_error_mapping_preserves_location(
    code: str,
    expected_status: int,
) -> None:
    component_id = uuid4()
    error = DashboardChartQueryError(
        code,
        "Query failed",
        "Correct the query",
        config_path="query.measures.0",
    )

    http_error = routes._chart_query_http_error(error, component_id=component_id)

    assert http_error.status_code == expected_status
    assert http_error.detail == {
        "code": code,
        "message": "Query failed",
        "action": "Correct the query",
        "location": {
            "component_id": str(component_id),
            "config_path": "query.measures.0",
        },
    }


def test_validate_route_passes_workspace_timezone_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = FastAPI()
    application.include_router(router, prefix="/dashboard-chart-queries")
    principal = QueryPrincipal(
        user_id=uuid4(),
        workspace_id=uuid4(),
        permissions=frozenset({"dashboards:view", "datasets:query"}),
    )

    def session_dependency() -> Generator[Session]:
        yield cast(Session, object())

    application.dependency_overrides[get_database_session] = session_dependency
    application.dependency_overrides[get_query_principal] = lambda: principal
    application.dependency_overrides[get_settings] = lambda: Settings(
        workspace_timezone="UTC",
        query_timeout_seconds=7,
    )
    ids: dict[str, UUID] = {
        "dashboard": uuid4(),
        "page": uuid4(),
        "component": uuid4(),
        "field": uuid4(),
    }
    captured: dict[str, object] = {}

    def fake_validate(
        _session: Session,
        *,
        principal: QueryPrincipal,
        request: object,
        workspace_timezone: str,
        timeout_seconds: float,
    ) -> DashboardChartValidation:
        captured.update(
            {
                "principal": principal,
                "request": request,
                "workspace_timezone": workspace_timezone,
                "timeout_seconds": timeout_seconds,
            }
        )
        return DashboardChartValidation(
            valid=True,
            component_id=ids["component"],
            columns=(
                ChartColumn(
                    slot_key="category",
                    query_alias="dimension",
                    resource_kind="field",
                    resource_id=ids["field"],
                    aggregate=None,
                    label="Category",
                    data_type="string",
                    unit=None,
                ),
            ),
            dataset_version=2,
            metric_version_ids=(),
            resolved_filters=(),
        )

    monkeypatch.setattr(routes, "validate_dashboard_chart_query", fake_validate)
    with TestClient(application) as client:
        response = cast(
            Response,
            client.post(
                "/dashboard-chart-queries/validate",
                json={
                    "dashboard_id": str(ids["dashboard"]),
                    "dashboard_version_id": str(uuid4()),
                    "page_id": str(ids["page"]),
                    "component_id": str(ids["component"]),
                },
            ),
        )

    assert response.status_code == 200
    assert response.json() == {
        "valid": True,
        "component_id": str(ids["component"]),
        "columns": [
            {
                "slot_key": "category",
                "query_alias": "dimension",
                "resource_kind": "field",
                "resource_id": str(ids["field"]),
                "aggregate": None,
                "label": "Category",
                "data_type": "string",
                "unit": None,
            }
        ],
        "dataset_version": 2,
        "metric_version_ids": [],
        "resolved_filters": [],
    }
    assert captured["principal"] is principal
    assert captured["workspace_timezone"] == "UTC"
    assert captured["timeout_seconds"] == 7


def test_endpoint_converts_service_error_without_exposing_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    component_id = uuid4()

    def fail(*_args: object, **_kwargs: object) -> DashboardChartValidation:
        raise DashboardChartQueryError(
            "dashboard_forbidden",
            "Dashboard view capability is required",
            "Ask the owner for access",
        )

    monkeypatch.setattr(routes, "validate_dashboard_chart_query", fail)
    with pytest.raises(HTTPException) as captured:
        routes.validate_dashboard_chart_query_endpoint(
            request_body=routes.DashboardChartQueryRequest(
                dashboard_id=uuid4(),
                dashboard_version_id=uuid4(),
                page_id=uuid4(),
                component_id=component_id,
            ),
            session=cast(Session, object()),
            actor=QueryPrincipal(
                user_id=uuid4(),
                workspace_id=uuid4(),
                permissions=frozenset(),
            ),
            settings=Settings(workspace_timezone="UTC"),
        )

    assert captured.value.status_code == 403
    detail = cast(dict[str, object], captured.value.detail)
    location = cast(dict[str, object], detail["location"])
    assert location["component_id"] == str(component_id)
