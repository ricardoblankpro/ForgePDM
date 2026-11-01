"""Four-character password policy and CLI account/password workflows."""

import pytest

from forgepdm import cli
from forgepdm.application.auth import AuthenticationError, hash_password, verify_password


@pytest.mark.parametrize("password", ["", "1", "12", "123"])
def test_passwords_shorter_than_four_characters_are_rejected(password):
    with pytest.raises(ValueError, match="at least 4 characters"):
        hash_password(password)


@pytest.mark.parametrize("password", ["1234", "abcd", "a much longer password", "áéíó"])
def test_numeric_and_text_passwords_at_or_above_minimum_verify(password):
    encoded = hash_password(password)
    assert verify_password(password, encoded)
    assert not verify_password(password + "wrong", encoded)


def test_password_upper_limit_remains_enforced():
    with pytest.raises(ValueError, match="too long"):
        hash_password("x" * 1025)


def test_cli_can_create_and_reset_a_four_digit_password(backend, monkeypatch):
    monkeypatch.setenv("FORGEPDM_DATABASE", str(backend.database.path))
    prompts = []

    def password_prompt(prompt):
        prompts.append(prompt)
        return "1234"

    monkeypatch.setattr(cli, "getpass", password_prompt)
    monkeypatch.setattr("sys.argv", ["forgepdm", "create-user", "short-password", "Test User"])
    cli.main()
    old_token, user, _ = backend.auth.login("short-password", "1234")
    assert user.username == "short-password"
    assert prompts == ["Password (at least 4 characters): ", "Confirm password: "]

    monkeypatch.setattr(cli, "getpass", lambda prompt: "5678")
    monkeypatch.setattr("sys.argv", ["forgepdm", "set-password", "short-password"])
    cli.main()
    assert backend.auth.login("short-password", "5678")[1].id == user.id
    with pytest.raises(AuthenticationError):
        backend.auth.login("short-password", "1234")
    with pytest.raises(AuthenticationError):
        backend.auth.authenticate(old_token)
