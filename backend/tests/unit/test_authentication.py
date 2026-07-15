from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from bi_system.db.base import Base
from bi_system.db.models import Role, User, UserRole, UserSession
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import (
    create_authenticated_session,
    hash_password,
    resolve_query_principal,
    verify_password,
)


def test_scrypt_password_hashes_use_random_salts_and_verify() -> None:
    password = "correct horse battery staple"
    first = hash_password(password)
    second = hash_password(password)

    assert first.startswith("scrypt$16384$8$1$")
    assert first != second
    assert verify_password(password, first) is True
    assert verify_password("wrong password", first) is False
    assert verify_password(password, "malformed") is False


def test_session_resolution_rejects_expired_and_disabled_users(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'auth.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    now = datetime.now(UTC)

    try:
        with session_factory.begin() as session:
            user = User(
                workspace_id=workspace_id,
                username="admin",
                display_name="Admin",
                password_hash=hash_password("a sufficiently strong password"),
                must_change_password=False,
            )
            role = Role(
                workspace_id=workspace_id,
                code="system_admin",
                name="System administrator",
                permissions=["datasets:query"],
            )
            session.add_all([user, role])
            session.flush()
            session.add(UserRole(user_id=user.id, role_id=role.id))

        with session_factory() as session:
            authenticated = create_authenticated_session(
                session,
                workspace_id=workspace_id,
                username=" ADMIN ",
                password="a sufficiently strong password",
                now=now,
            )
        assert authenticated is not None

        with session_factory() as session:
            principal = resolve_query_principal(
                session,
                workspace_id=workspace_id,
                token=authenticated.token,
                now=now + timedelta(minutes=1),
            )
            expired = resolve_query_principal(
                session,
                workspace_id=workspace_id,
                token=authenticated.token,
                now=authenticated.expires_at + timedelta(seconds=1),
            )
        assert principal is not None
        assert principal.is_system_admin is True
        assert principal.has_permission("datasets:query") is True
        assert expired is None

        with session_factory.begin() as session:
            stored_user = session.get(User, authenticated.user.id)
            assert stored_user is not None
            stored_user.status = "disabled"
        with session_factory() as session:
            assert (
                resolve_query_principal(
                    session,
                    workspace_id=workspace_id,
                    token=authenticated.token,
                    now=now + timedelta(minutes=2),
                )
                is None
            )
            assert session.query(UserSession).count() == 1
    finally:
        engine.dispose()
