import argparse
import getpass
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from bi_system.core.config import get_settings
from bi_system.db.models import Role, User, UserRole
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import hash_password
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session


class InitialAdminError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CreatedAdmin:
    user_id: UUID
    role_id: UUID
    workspace_id: UUID
    username: str


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create the first local system administrator explicitly",
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name")
    parser.add_argument("--workspace-id", type=UUID)
    password_source = parser.add_mutually_exclusive_group()
    password_source.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read one password line from standard input",
    )
    password_source.add_argument(
        "--password-env-var",
        metavar="NAME",
        help="Read the password from the named environment variable",
    )
    return parser


def create_initial_admin(
    session: Session,
    *,
    workspace_id: UUID,
    username: str,
    display_name: str,
    password: str,
) -> CreatedAdmin:
    normalized_username = username.strip().lower()
    normalized_display_name = display_name.strip()
    if not normalized_username or len(normalized_username) > 128:
        raise InitialAdminError("Username must contain between 1 and 128 characters")
    if not normalized_display_name or len(normalized_display_name) > 128:
        raise InitialAdminError("Display name must contain between 1 and 128 characters")

    try:
        with session.begin():
            existing_user = session.scalar(
                select(User.id).where(
                    User.workspace_id == workspace_id,
                    func.lower(User.username) == normalized_username,
                ),
            )
            if existing_user is not None:
                raise InitialAdminError(
                    f"User {normalized_username!r} already exists in this workspace",
                )

            role = session.scalar(
                select(Role).where(
                    Role.workspace_id == workspace_id,
                    Role.code == "system_admin",
                ),
            )
            if role is not None and role.status != "active":
                raise InitialAdminError(
                    "The system_admin role exists but is not active; restore it explicitly",
                )
            if role is None:
                role = Role(
                    workspace_id=workspace_id,
                    code="system_admin",
                    name="System Administrator",
                    description="Full local system administration access",
                    permissions=[],
                    status="active",
                )
                session.add(role)
                session.flush()

            user = User(
                workspace_id=workspace_id,
                username=normalized_username,
                display_name=normalized_display_name,
                password_hash=hash_password(password),
                status="active",
                must_change_password=False,
            )
            session.add(user)
            session.flush()
            session.add(UserRole(user_id=user.id, role_id=role.id))
            result = CreatedAdmin(
                user_id=user.id,
                role_id=role.id,
                workspace_id=workspace_id,
                username=user.username,
            )
    except IntegrityError as exc:
        raise InitialAdminError(
            "Administrator creation conflicted with an existing user or role",
        ) from exc
    return result


def read_password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise InitialAdminError("No password was received from standard input")
        return password
    if args.password_env_var:
        password = os.environ.get(args.password_env_var)
        if not password:
            raise InitialAdminError(
                f"Environment variable {args.password_env_var!r} is missing or empty",
            )
        return password

    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise InitialAdminError("Password confirmation does not match")
    return password


def main(argv: Sequence[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    settings = get_settings()
    workspace_id = args.workspace_id or settings.workspace_id
    display_name = args.display_name or args.username
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        password = read_password(args)
        with session_factory() as session:
            created = create_initial_admin(
                session,
                workspace_id=workspace_id,
                username=args.username,
                display_name=display_name,
                password=password,
            )
    except (InitialAdminError, ValueError) as exc:
        print(f"Administrator was not created: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print(
            "Administrator was not created: database operation failed; apply migrations first",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()

    print(
        f"Created system administrator user_id={created.user_id} "
        f"workspace_id={created.workspace_id} username={created.username}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
