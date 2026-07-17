# pyright: reportUnknownMemberType=false
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from bi_system.api.dependencies import get_database_session, get_query_principal
from bi_system.api.routes.semantic_models import router
from bi_system.db.base import Base
from bi_system.db.models import ImportColumn, ImportTarget, User
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session


@pytest.fixture
def semantic_model_api(
    tmp_path: Path,
) -> Generator[tuple[TestClient, dict[str, str], dict[str, QueryPrincipal]]]:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'api.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    with session_factory.begin() as session:
        user = User(
            workspace_id=workspace_id,
            username="api.admin",
            display_name="API Admin",
            password_hash="hash",
            must_change_password=False,
        )
        fact = ImportTarget(
            workspace_id=workspace_id,
            name="Fact",
            physical_table_name=f"data_{uuid4().hex}",
            status="active",
        )
        dimension = ImportTarget(
            workspace_id=workspace_id,
            name="Dimension",
            physical_table_name=f"data_{uuid4().hex}",
            status="active",
        )
        session.add_all([user, fact, dimension])
        session.flush()
        fact_key = ImportColumn(
            target_id=fact.id,
            source_name="City",
            physical_name="city_id",
            data_type="string",
            nullable=False,
            ordinal=0,
        )
        dimension_key = ImportColumn(
            target_id=dimension.id,
            source_name="City",
            physical_name="city_id",
            data_type="string",
            nullable=False,
            ordinal=0,
        )
        session.add_all([fact_key, dimension_key])
        session.flush()
        values = {
            "workspace_id": str(workspace_id),
            "user_id": str(user.id),
            "fact_id": str(fact.id),
            "dimension_id": str(dimension.id),
            "fact_key": str(fact_key.id),
            "dimension_key": str(dimension_key.id),
        }

    application = FastAPI()
    application.include_router(router, prefix="/semantic-models")

    def session_dependency() -> Generator[Session]:
        with session_factory() as session:
            yield session

    principal = QueryPrincipal(
        user_id=user.id,
        workspace_id=workspace_id,
        permissions=frozenset({"datasets:manage"}),
    )
    actor = {"value": principal}
    application.dependency_overrides[get_database_session] = session_dependency
    application.dependency_overrides[get_query_principal] = lambda: actor["value"]
    try:
        with TestClient(application) as client:
            yield client, values, actor
    finally:
        engine.dispose()


def api_payload(values: dict[str, str]) -> dict[str, Any]:
    return {
        "name": "API model",
        "sources": [
            {"target_id": values["fact_id"], "alias": "fact", "role": "fact"},
            {
                "target_id": values["dimension_id"],
                "alias": "dimension",
                "role": "dimension",
            },
        ],
        "joins": [
            {
                "left_source": "fact",
                "right_source": "dimension",
                "join_type": "inner",
                "cardinality": "many_to_one",
                "keys": [
                    {
                        "left_column_id": values["fact_key"],
                        "right_column_id": values["dimension_key"],
                    },
                ],
            },
        ],
    }


def test_api_validates_creates_lists_and_reads_model(
    semantic_model_api: tuple[TestClient, dict[str, str], dict[str, QueryPrincipal]],
) -> None:
    client, values, _actor = semantic_model_api
    validated = cast(
        Response,
        client.post("/semantic-models/validate", json=api_payload(values)),
    )
    created = cast(Response, client.post("/semantic-models", json=api_payload(values)))
    listed = cast(Response, client.get("/semantic-models"))
    read = cast(Response, client.get(f"/semantic-models/{created.json()['id']}"))

    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    assert created.status_code == 201
    assert created.json()["version"] == 1
    assert len(created.json()["joins"][0]["keys"]) == 1
    assert [item["id"] for item in listed.json()] == [created.json()["id"]]
    assert read.json()["series_id"] == created.json()["series_id"]


def test_api_returns_structured_validation_and_not_found_errors(
    semantic_model_api: tuple[TestClient, dict[str, str], dict[str, QueryPrincipal]],
) -> None:
    client, values, _actor = semantic_model_api
    mismatched = api_payload(values)
    mismatched["joins"][0]["keys"][0]["left_column_id"] = values["dimension_key"]

    invalid = cast(Response, client.post("/semantic-models/validate", json=mismatched))
    missing = cast(Response, client.get(f"/semantic-models/{uuid4()}"))

    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "semantic_model_join_field_mismatch"
    assert invalid.json()["detail"]["action"]
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "semantic_model_not_found"


def test_api_activation_archives_previous_version_and_enforces_write_permission(
    semantic_model_api: tuple[TestClient, dict[str, str], dict[str, QueryPrincipal]],
) -> None:
    client, values, actor = semantic_model_api
    first = cast(Response, client.post("/semantic-models", json=api_payload(values)))
    activated_first = cast(
        Response,
        client.post(f"/semantic-models/{first.json()['id']}/activate"),
    )
    second_payload = api_payload(values)
    second_payload["series_id"] = str(uuid4())
    second = cast(
        Response,
        client.post(
            f"/semantic-models/{first.json()['id']}/versions",
            json=second_payload,
        ),
    )
    assert second.status_code == 201
    assert second.json()["version"] == 2
    assert second.json()["series_id"] == first.json()["series_id"]

    actor["value"] = QueryPrincipal(
        user_id=actor["value"].user_id,
        workspace_id=actor["value"].workspace_id,
    )
    forbidden_validate = cast(
        Response,
        client.post("/semantic-models/validate", json=api_payload(values)),
    )
    forbidden_create = cast(Response, client.post("/semantic-models", json=api_payload(values)))
    forbidden_version = cast(
        Response,
        client.post(
            f"/semantic-models/{first.json()['id']}/versions",
            json=api_payload(values),
        ),
    )
    forbidden_activate = cast(
        Response,
        client.post(f"/semantic-models/{second.json()['id']}/activate"),
    )
    readable = cast(Response, client.get(f"/semantic-models/{second.json()['id']}"))

    assert activated_first.status_code == 200
    assert activated_first.json()["status"] == "active"
    assert forbidden_validate.status_code == 403
    assert forbidden_create.status_code == 403
    assert forbidden_version.status_code == 403
    assert forbidden_activate.status_code == 403
    assert forbidden_activate.json()["detail"]["code"] == "semantic_model_manage_forbidden"
    assert readable.status_code == 200

    actor["value"] = QueryPrincipal(
        user_id=actor["value"].user_id,
        workspace_id=actor["value"].workspace_id,
        permissions=frozenset({"datasets:manage"}),
    )
    activated_second = cast(
        Response,
        client.post(f"/semantic-models/{second.json()['id']}/activate"),
    )
    archived_first = cast(Response, client.get(f"/semantic-models/{first.json()['id']}"))

    assert activated_second.status_code == 200
    assert activated_second.json()["status"] == "active"
    assert archived_first.json()["status"] == "archived"


def test_api_activation_hides_cross_workspace_model(
    semantic_model_api: tuple[TestClient, dict[str, str], dict[str, QueryPrincipal]],
) -> None:
    client, values, actor = semantic_model_api
    created = cast(Response, client.post("/semantic-models", json=api_payload(values)))
    actor["value"] = QueryPrincipal(
        user_id=actor["value"].user_id,
        workspace_id=uuid4(),
        permissions=frozenset({"datasets:manage"}),
    )

    response = cast(
        Response,
        client.post(f"/semantic-models/{created.json()['id']}/activate"),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "semantic_model_not_found"
