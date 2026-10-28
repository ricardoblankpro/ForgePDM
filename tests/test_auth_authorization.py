from datetime import datetime, timezone

import pytest

from forgepdm.application.auth import AuthenticationError
from forgepdm.domain.entities import Forbidden

from conftest import TEST_PASSWORD, create_item


def test_password_login_issues_hashed_revocable_session(backend):
    token, user, expires_at = backend.auth.login("EDITOR", TEST_PASSWORD)

    assert user.id == backend.users["editor"].id
    assert expires_at > datetime.now(timezone.utc)
    assert backend.auth.authenticate(token).id == user.id
    with backend.database.connection() as connection:
        stored_hash = connection.execute(
            "SELECT token_hash FROM auth_sessions WHERE user_id = ?", (user.id,)
        ).fetchone()["token_hash"]
    assert stored_hash != token

    backend.auth.logout(token, user.id)
    with pytest.raises(AuthenticationError):
        backend.auth.authenticate(token)


def test_login_rejects_bad_credentials(backend):
    with pytest.raises(AuthenticationError):
        backend.auth.login("editor", "not the password")
    with pytest.raises(AuthenticationError):
        backend.auth.login("missing-user", TEST_PASSWORD)


def test_project_membership_controls_item_access(backend):
    item = create_item(backend)
    backend.authorization.require_read_item(backend.users["viewer"], item.id)
    with pytest.raises(Forbidden):
        backend.authorization.require_create_item(backend.users["viewer"], backend.project_id)
    with pytest.raises(Forbidden):
        backend.authorization.require_create_item(backend.users["editor"], None)


def test_unprojected_item_is_admin_only(backend):
    from forgepdm.domain.entities import ItemKind

    item = backend.items.create_item(
        kind=ItemKind.PART,
        name="Private Item",
        description="",
        created_by=backend.users["admin"].id,
    )
    backend.authorization.require_read_item(backend.users["admin"], item.id)
    with pytest.raises(Forbidden):
        backend.authorization.require_read_item(backend.users["viewer"], item.id)
