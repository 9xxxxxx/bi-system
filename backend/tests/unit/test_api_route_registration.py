from typing import Any, cast

from bi_system.main import create_app


def test_auth_and_dataset_query_routes_are_registered_in_application() -> None:
    paths = cast(dict[str, dict[str, Any]], create_app().openapi()["paths"])

    expected_methods = {
        "/api/v1/auth/login": {"post"},
        "/api/v1/auth/me": {"get"},
        "/api/v1/auth/logout": {"post"},
        "/api/v1/dataset-queries/validate": {"post"},
        "/api/v1/dataset-queries": {"post"},
    }
    for path, methods in expected_methods.items():
        assert path in paths
        assert set(paths[path]) == methods
