from unittest.mock import Mock
from uuid import uuid4

import pytest
from bi_system.api.dependencies import get_query_principal
from bi_system.core.config import Settings
from bi_system.identity import QueryPrincipal
from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request


def request_with_state() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def test_query_principal_permission_check() -> None:
    principal = QueryPrincipal(
        user_id=uuid4(),
        workspace_id=uuid4(),
        role_ids=frozenset({uuid4()}),
        permissions=frozenset({"datasets:query"}),
    )
    assert principal.has_permission("datasets:query") is True
    assert principal.has_permission("datasets:manage") is False


def test_system_admin_principal_has_all_permissions() -> None:
    principal = QueryPrincipal(user_id=uuid4(), workspace_id=uuid4(), is_system_admin=True)
    assert principal.has_permission("any:permission") is True


def test_query_principal_dependency_rejects_missing_authentication() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_query_principal(
            request_with_state(),
            Mock(spec=Session),
            Settings(environment="test"),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == {
        "code": "authentication_required",
        "message": "Authentication is required",
        "action": "Sign in and try again",
    }


def test_query_principal_dependency_ends_authentication_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = QueryPrincipal(user_id=uuid4(), workspace_id=uuid4())
    session = Mock(spec=Session)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", b"bi_session=session-token")],
        }
    )

    def resolve_principal(
        _session: Session,
        *,
        workspace_id: object,
        token: str,
    ) -> QueryPrincipal:
        assert workspace_id == principal.workspace_id
        assert token == "session-token"
        return principal

    monkeypatch.setattr(
        "bi_system.api.dependencies.resolve_query_principal",
        resolve_principal,
    )

    resolved = get_query_principal(
        request,
        session,
        Settings(environment="test", workspace_id=principal.workspace_id),
    )

    assert resolved == principal
    session.rollback.assert_called_once_with()
