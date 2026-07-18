from typing import Any, cast

from bi_system.main import create_app


def test_auth_dataset_query_and_dashboard_routes_are_registered() -> None:
    paths = cast(dict[str, dict[str, Any]], create_app().openapi()["paths"])

    expected_methods = {
        "/api/v1/auth/login": {"post"},
        "/api/v1/auth/me": {"get"},
        "/api/v1/auth/logout": {"post"},
        "/api/v1/dataset-queries/validate": {"post"},
        "/api/v1/dataset-queries": {"post"},
        "/api/v1/dashboard-chart-queries/validate": {"post"},
        "/api/v1/dashboard-chart-queries": {"post"},
        "/api/v1/dashboards": {"get", "post"},
        "/api/v1/dashboards/{dashboard_id}": {"get", "delete"},
        "/api/v1/dashboards/{dashboard_id}/versions": {"post"},
        "/api/v1/dashboards/{dashboard_id}/permissions": {"put"},
        "/api/v1/dashboards/{dashboard_id}/restore": {"post"},
        "/api/v1/dashboard-templates": {"get", "post"},
        "/api/v1/dashboard-templates/{template_id}": {"get"},
    }
    for path, methods in expected_methods.items():
        assert path in paths
        assert set(paths[path]) == methods
