import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from bi_system.db.models import Role, User, UserRole, UserSession
from bi_system.identity.principal import QueryPrincipal

PASSWORD_SCHEME = "scrypt"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SALT_BYTES = 16
SESSION_TOKEN_BYTES = 48
SESSION_TTL = timedelta(hours=12)
MAX_FAILED_LOGIN_ATTEMPTS = 5
_DUMMY_SALT = b"\x00" * SALT_BYTES
_DUMMY_DIGEST = hashlib.scrypt(
    b"invalid authentication attempt",
    salt=_DUMMY_SALT,
    n=SCRYPT_N,
    r=SCRYPT_R,
    p=SCRYPT_P,
    dklen=SCRYPT_DKLEN,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    user: User
    principal: QueryPrincipal
    token: str
    expires_at: datetime


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive_password(password, salt=salt)
    return "$".join(
        (
            PASSWORD_SCHEME,
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _encode_bytes(salt),
            _encode_bytes(digest),
        ),
    )


def verify_password(password: str, encoded_password: str) -> bool:
    try:
        scheme, n_text, r_text, p_text, salt_text, digest_text = encoded_password.split("$")
        if (
            scheme != PASSWORD_SCHEME
            or int(n_text) != SCRYPT_N
            or int(r_text) != SCRYPT_R
            or int(p_text) != SCRYPT_P
        ):
            return False
        salt = _decode_bytes(salt_text)
        expected = _decode_bytes(digest_text)
        if len(salt) != SALT_BYTES or len(expected) != SCRYPT_DKLEN:
            return False
        actual = _derive_password(password, salt=salt)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def create_authenticated_session(
    session: Session,
    *,
    workspace_id: UUID,
    username: str,
    password: str,
    now: datetime | None = None,
) -> AuthenticatedSession | None:
    current_time = now or datetime.now(UTC)
    normalized_username = username.strip().lower()
    with session.begin():
        user = session.scalar(
            select(User).where(
                User.workspace_id == workspace_id,
                User.username == normalized_username,
            ),
        )
        password_hash = user.password_hash if user is not None else _dummy_password_hash()
        password_valid = verify_password(password, password_hash)
        if user is None or user.status != "active" or not password_valid:
            if user is None or user.status != "active":
                return None
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED_LOGIN_ATTEMPTS:
                user.status = "locked"
            return None

        user.failed_login_count = 0
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        expires_at = current_time + SESSION_TTL
        session.add(
            UserSession(
                user_id=user.id,
                token_hash=hash_session_token(token),
                expires_at=expires_at,
                created_at=current_time,
            ),
        )
        principal = _principal_for_user(session, user=user)
    return AuthenticatedSession(
        user=user,
        principal=principal,
        token=token,
        expires_at=expires_at,
    )


def resolve_query_principal(
    session: Session,
    *,
    workspace_id: UUID,
    token: str,
    now: datetime | None = None,
) -> QueryPrincipal | None:
    current_time = now or datetime.now(UTC)
    stored_session = session.scalar(
        select(UserSession).where(
            UserSession.token_hash == hash_session_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > current_time,
        ),
    )
    if stored_session is None:
        return None
    user = session.get(User, stored_session.user_id)
    if user is None or user.workspace_id != workspace_id or user.status != "active":
        return None
    return _principal_for_user(session, user=user)


def revoke_session_token(
    session: Session,
    *,
    token: str,
    now: datetime | None = None,
) -> None:
    current_time = now or datetime.now(UTC)
    with session.begin():
        stored_session = session.scalar(
            select(UserSession).where(UserSession.token_hash == hash_session_token(token)),
        )
        if stored_session is not None and stored_session.revoked_at is None:
            stored_session.revoked_at = current_time


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _principal_for_user(session: Session, *, user: User) -> QueryPrincipal:
    roles = session.scalars(
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user.id,
            Role.workspace_id == user.workspace_id,
            Role.status == "active",
        )
        .order_by(Role.code),
    ).all()
    permissions = frozenset(permission for role in roles for permission in role.permissions)
    return QueryPrincipal(
        user_id=user.id,
        workspace_id=user.workspace_id,
        role_ids=frozenset(role.id for role in roles),
        permissions=permissions,
        is_system_admin=any(role.code == "system_admin" for role in roles),
    )


def _derive_password(password: str, *, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _dummy_password_hash() -> str:
    return "$".join(
        (
            PASSWORD_SCHEME,
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _encode_bytes(_DUMMY_SALT),
            _encode_bytes(_DUMMY_DIGEST),
        ),
    )
