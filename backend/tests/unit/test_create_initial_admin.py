from pathlib import Path

import pytest
from bi_system.core.config import clear_settings_cache
from bi_system.db.base import Base
from bi_system.db.models import Role, User, UserRole
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import verify_password
from sqlalchemy import func, select

from scripts import create_initial_admin as admin_cli


def test_create_initial_admin_binds_system_role_and_rejects_duplicate(tmp_path: Path) -> None:
    engine = create_database_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'initial-admin.db').as_posix()}",
    )
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    workspace_id = admin_cli.UUID("00000000-0000-0000-0000-000000000001")
    password = "correct horse battery staple"

    try:
        with session_factory() as session:
            created = admin_cli.create_initial_admin(
                session,
                workspace_id=workspace_id,
                username=" Admin ",
                display_name="系统管理员",
                password=password,
            )

        with session_factory() as session:
            user = session.get(User, created.user_id)
            role = session.get(Role, created.role_id)
            assignment = session.scalar(
                select(UserRole).where(
                    UserRole.user_id == created.user_id,
                    UserRole.role_id == created.role_id,
                ),
            )
            assert user is not None
            assert user.username == "admin"
            assert verify_password(password, user.password_hash) is True
            assert password not in user.password_hash
            assert role is not None
            assert role.code == "system_admin"
            assert role.status == "active"
            assert assignment is not None

        with (
            session_factory() as session,
            pytest.raises(admin_cli.InitialAdminError, match="already exists"),
        ):
            admin_cli.create_initial_admin(
                session,
                workspace_id=workspace_id,
                username="ADMIN",
                display_name="Other Admin",
                password="a different strong password",
            )

        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 1
            assert session.scalar(select(func.count()).select_from(Role)) == 1
            assert session.scalar(select(func.count()).select_from(UserRole)) == 1
    finally:
        engine.dispose()


def test_cli_reads_password_from_named_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "not printed anywhere"
    monkeypatch.setenv("TEST_INITIAL_ADMIN_SECRET", secret)
    args = admin_cli.argument_parser().parse_args(
        ["--username", "admin", "--password-env-var", "TEST_INITIAL_ADMIN_SECRET"],
    )

    assert admin_cli.read_password(args) == secret


def test_cli_duplicate_returns_clear_error_without_printing_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "cli.db"
    monkeypatch.setenv("BI_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("TEST_INITIAL_ADMIN_SECRET", "correct horse battery staple")
    clear_settings_cache()
    engine = create_database_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    arguments = [
        "--username",
        "admin",
        "--display-name",
        "Administrator",
        "--password-env-var",
        "TEST_INITIAL_ADMIN_SECRET",
    ]

    try:
        assert admin_cli.main(arguments) == 0
        first_output = capsys.readouterr()
        assert "correct horse battery staple" not in first_output.out
        assert "correct horse battery staple" not in first_output.err

        assert admin_cli.main(arguments) == 2
        duplicate_output = capsys.readouterr()
        assert "already exists" in duplicate_output.err
        assert "correct horse battery staple" not in duplicate_output.err
    finally:
        clear_settings_cache()
