# pyright: reportUnknownMemberType=false
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from bi_system.api.routes import auth
from bi_system.core.config import clear_settings_cache, get_settings
from bi_system.db.base import Base
from bi_system.db.models import Role, User, UserRole, UserSession
from bi_system.identity import hash_password, hash_session_token
from bi_system.main import create_app
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class AuthApiContext:
    client: TestClient
    session_factory: sessionmaker[Session]
    user_id: UUID
    disabled_username: str


@pytest.fixture
def auth_api_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[AuthApiContext]:
    database_path = tmp_path / "auth-api.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("BI_STORAGE_ROOT", str(tmp_path / "uploads"))
    clear_settings_cache()
    application = create_app()
    application.include_router(auth.router, prefix="/api/v1/auth")

    with TestClient(application) as client:
        Base.metadata.create_all(cast(Engine, application.state.engine))
        session_factory = cast(sessionmaker[Session], application.state.session_factory)
        workspace_id = get_settings().workspace_id
        with session_factory.begin() as session:
            user = User(
                workspace_id=workspace_id,
                username="admin",
                display_name="系统管理员",
                password_hash=hash_password("correct horse battery staple"),
                must_change_password=False,
            )
            disabled = User(
                workspace_id=workspace_id,
                username="disabled",
                display_name="停用用户",
                password_hash=hash_password("another sufficiently strong password"),
                status="disabled",
            )
            role = Role(
                workspace_id=workspace_id,
                code="system_admin",
                name="系统管理员",
                permissions=["datasets:manage", "datasets:query"],
            )
            session.add_all([user, disabled, role])
            session.flush()
            session.add(UserRole(user_id=user.id, role_id=role.id))
            user_id = user.id

        yield AuthApiContext(
            client=client,
            session_factory=session_factory,
            user_id=user_id,
            disabled_username=disabled.username,
        )

    clear_settings_cache()


def test_login_me_and_logout_use_hashed_revocable_cookie(
    auth_api_context: AuthApiContext,
) -> None:
    login = cast(
        Response,
        auth_api_context.client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "correct horse battery staple"},
        ),
    )

    assert login.status_code == 200, login.text
    assert login.json() == {
        "id": str(auth_api_context.user_id),
        "workspace_id": str(get_settings().workspace_id),
        "username": "admin",
        "display_name": "系统管理员",
        "must_change_password": False,
        "role_ids": login.json()["role_ids"],
        "permissions": ["datasets:manage", "datasets:query"],
        "is_system_admin": True,
    }
    assert len(login.json()["role_ids"]) == 1
    set_cookie = login.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie
    assert "secure" not in set_cookie
    raw_token = cast(str | None, auth_api_context.client.cookies.get("bi_session"))
    assert raw_token is not None
    assert len(raw_token) >= 64

    with auth_api_context.session_factory() as session:
        stored_session = session.scalar(select(UserSession))
        assert stored_session is not None
        assert stored_session.token_hash == hash_session_token(raw_token)
        assert raw_token not in stored_session.token_hash

    me = cast(Response, auth_api_context.client.get("/api/v1/auth/me"))
    assert me.status_code == 200
    assert me.json()["id"] == str(auth_api_context.user_id)

    logout = cast(Response, auth_api_context.client.post("/api/v1/auth/logout"))
    assert logout.status_code == 204
    with auth_api_context.session_factory() as session:
        stored_session = session.scalar(select(UserSession))
        assert stored_session is not None
        assert stored_session.revoked_at is not None

    auth_api_context.client.cookies.set("bi_session", raw_token)
    rejected = cast(Response, auth_api_context.client.get("/api/v1/auth/me"))
    assert rejected.status_code == 401
    assert rejected.json()["detail"]["code"] == "authentication_required"


def test_login_uses_generic_error_and_tracks_failed_attempt(
    auth_api_context: AuthApiContext,
) -> None:
    response = cast(
        Response,
        auth_api_context.client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "incorrect password"},
        ),
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"
    assert "bi_session" not in response.cookies
    with auth_api_context.session_factory() as session:
        user = session.get(User, auth_api_context.user_id)
        assert user is not None
        assert user.failed_login_count == 1


def test_login_locks_account_after_repeated_failures(
    auth_api_context: AuthApiContext,
) -> None:
    for _attempt in range(5):
        response = cast(
            Response,
            auth_api_context.client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "incorrect password"},
            ),
        )
        assert response.status_code == 401

    with auth_api_context.session_factory() as session:
        user = session.get(User, auth_api_context.user_id)
        assert user is not None
        assert user.failed_login_count == 5
        assert user.status == "locked"

    correct_password = cast(
        Response,
        auth_api_context.client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "correct horse battery staple"},
        ),
    )
    assert correct_password.status_code == 401


def test_login_rejects_disabled_and_cross_workspace_users(
    auth_api_context: AuthApiContext,
) -> None:
    disabled = cast(
        Response,
        auth_api_context.client.post(
            "/api/v1/auth/login",
            json={
                "username": auth_api_context.disabled_username,
                "password": "another sufficiently strong password",
            },
        ),
    )
    missing = cast(
        Response,
        auth_api_context.client.post(
            "/api/v1/auth/login",
            json={"username": "missing", "password": "another strong password"},
        ),
    )

    assert disabled.status_code == 401
    assert missing.status_code == 401
    assert disabled.json()["detail"] == missing.json()["detail"]
