# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from bi_system.core.config import clear_settings_cache
from bi_system.db.base import Base
from bi_system.db.models import ImportTarget, Role, User, UserRole
from bi_system.identity import hash_password
from bi_system.main import create_app
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class SemanticModelAuthContext:
    client: TestClient
    session_factory: sessionmaker[Session]
    target_id: UUID


@pytest.fixture
def semantic_model_auth_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[SemanticModelAuthContext]:
    workspace_id = uuid4()
    database_path = tmp_path / "semantic-model-auth.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("BI_WORKSPACE_ID", str(workspace_id))
    clear_settings_cache()
    application = create_app()

    with TestClient(application) as client:
        Base.metadata.create_all(cast(Engine, application.state.engine))
        session_factory = cast(sessionmaker[Session], application.state.session_factory)
        with session_factory.begin() as session:
            manager = User(
                workspace_id=workspace_id,
                username="model-manager",
                display_name="Model Manager",
                password_hash=hash_password("manager password for tests"),
                must_change_password=False,
            )
            reader = User(
                workspace_id=workspace_id,
                username="model-reader",
                display_name="Model Reader",
                password_hash=hash_password("reader password for tests"),
                must_change_password=False,
            )
            manager_role = Role(
                workspace_id=workspace_id,
                code="model_manager",
                name="Model manager",
                permissions=["datasets:manage"],
            )
            reader_role = Role(
                workspace_id=workspace_id,
                code="model_reader",
                name="Model reader",
                permissions=[],
            )
            target = ImportTarget(
                workspace_id=workspace_id,
                name="Sales fact",
                physical_table_name=f"data_{uuid4().hex}",
                status="active",
            )
            session.add_all([manager, reader, manager_role, reader_role, target])
            session.flush()
            session.add_all(
                [
                    UserRole(user_id=manager.id, role_id=manager_role.id),
                    UserRole(user_id=reader.id, role_id=reader_role.id),
                ],
            )
        yield SemanticModelAuthContext(
            client=client,
            session_factory=session_factory,
            target_id=target.id,
        )

    clear_settings_cache()


def _payload(context: SemanticModelAuthContext) -> dict[str, object]:
    return {
        "name": "Authenticated model",
        "sources": [
            {
                "target_id": str(context.target_id),
                "alias": "fact",
                "role": "fact",
            },
        ],
        "joins": [],
    }


def _login(client: TestClient, *, username: str, password: str) -> None:
    response = cast(
        Response,
        client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        ),
    )
    assert response.status_code == 200, response.text


def test_real_session_permissions_keep_reads_open_and_protect_model_writes(
    semantic_model_auth_context: SemanticModelAuthContext,
) -> None:
    context = semantic_model_auth_context
    _login(
        context.client,
        username="model-manager",
        password="manager password for tests",
    )
    validated = cast(
        Response,
        context.client.post("/api/v1/semantic-models/validate", json=_payload(context)),
    )
    created = cast(
        Response,
        context.client.post("/api/v1/semantic-models", json=_payload(context)),
    )
    activated = cast(
        Response,
        context.client.post(f"/api/v1/semantic-models/{created.json()['id']}/activate"),
    )
    assert validated.status_code == 200
    assert created.status_code == 201
    assert activated.status_code == 200

    logout = cast(Response, context.client.post("/api/v1/auth/logout"))
    assert logout.status_code == 204
    _login(
        context.client,
        username="model-reader",
        password="reader password for tests",
    )
    listed = cast(Response, context.client.get("/api/v1/semantic-models"))
    read = cast(
        Response,
        context.client.get(f"/api/v1/semantic-models/{created.json()['id']}"),
    )
    forbidden_requests = [
        cast(
            Response,
            context.client.post("/api/v1/semantic-models/validate", json=_payload(context)),
        ),
        cast(
            Response,
            context.client.post("/api/v1/semantic-models", json=_payload(context)),
        ),
        cast(
            Response,
            context.client.post(
                f"/api/v1/semantic-models/{created.json()['id']}/versions",
                json=_payload(context),
            ),
        ),
        cast(
            Response,
            context.client.post(f"/api/v1/semantic-models/{created.json()['id']}/activate"),
        ),
    ]

    assert listed.status_code == 200
    assert read.status_code == 200
    assert all(response.status_code == 403 for response in forbidden_requests)
    assert all(
        response.json()["detail"]["code"] == "semantic_model_manage_forbidden"
        for response in forbidden_requests
    )
