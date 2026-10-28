"""Password authentication and opaque bearer-session management."""

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from forgepdm.domain.entities import User
from forgepdm.infrastructure.database import Database


SESSION_DURATION = timedelta(hours=8)
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1


class AuthenticationError(Exception):
    """Credentials or bearer token are invalid or expired."""


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    if len(password) > 1024:
        raise ValueError("password is too long")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=32,
    )
    return "scrypt${}${}${}${}${}".format(
        PASSWORD_SCRYPT_N,
        PASSWORD_SCRYPT_R,
        PASSWORD_SCRYPT_P,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


DUMMY_PASSWORD_HASH = hash_password("forgepdm-dummy-login-secret")


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or len(password) > 1024:
        return False
    try:
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _user(row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        enabled=bool(row["enabled"]),
        role=row["role"],
    )


class AuthService:
    def __init__(self, database: Database):
        self.database = database

    def login(self, username: str, password: str) -> tuple[str, User, datetime]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT id, username, display_name, enabled, role, password_hash "
                "FROM users WHERE username = ? COLLATE NOCASE",
                (username.strip(),),
            ).fetchone()
        valid_password = verify_password(
            password, row["password_hash"] if row is not None else DUMMY_PASSWORD_HASH
        )
        if row is None or not row["enabled"] or not valid_password:
            raise AuthenticationError("invalid username or password")

        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + SESSION_DURATION
        with self.database.transaction() as connection:
            current = connection.execute(
                "SELECT enabled, password_hash FROM users WHERE id = ?", (row["id"],)
            ).fetchone()
            if (
                current is None
                or not current["enabled"]
                or current["password_hash"] != row["password_hash"]
            ):
                raise AuthenticationError("invalid username or password")
            connection.execute(
                "INSERT INTO auth_sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_token_hash(token), row["id"], now.isoformat(), expires_at.isoformat()),
            )
            connection.execute(
                "INSERT INTO audit_events(id, actor_id, event_type, entity_type, entity_id, occurred_at) "
                "VALUES (?, ?, 'auth.login', 'User', ?, ?)",
                (str(uuid4()), row["id"], row["id"], now.isoformat()),
            )
        return token, _user(row), expires_at

    def authenticate(self, token: str) -> User:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT u.id, u.username, u.display_name, u.enabled, u.role "
                "FROM auth_sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ? AND u.enabled = 1",
                (_token_hash(token), now),
            ).fetchone()
        if row is None:
            raise AuthenticationError("invalid or expired bearer token")
        return _user(row)

    def logout(self, token: str, user_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND user_id = ? AND revoked_at IS NULL",
                (now, _token_hash(token), user_id),
            )
            connection.execute(
                "INSERT INTO audit_events(id, actor_id, event_type, entity_type, entity_id, occurred_at) "
                "VALUES (?, ?, 'auth.logout', 'User', ?, ?)",
                (str(uuid4()), user_id, user_id, now),
            )

