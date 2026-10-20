"""Policy di sicurezza delle password impostate dall'admin."""

from __future__ import annotations

import pytest

from src.data.user_password import password_policy_violations


@pytest.mark.parametrize(
    "password",
    ["Str0ng!pw", "Aa1!aaaa", "Correct-Horse-9", "Pässwörd1€"],
)
def test_valid_passwords(password):
    assert password_policy_violations(password) == []


@pytest.mark.parametrize(
    "password, code",
    [
        ("Aa1!aaa", "too_short"),
        ("AA1!AAAA", "lowercase"),
        ("aa1!aaaa", "uppercase"),
        ("Aab!aaaa", "digit"),
        ("Aa1aaaaa", "symbol"),
        ("Aa1 aaaa", "symbol"),
        ("A1!" + "a" * 600, "too_long"),
        ("", "too_short"),
    ],
)
def test_invalid_passwords(password, code):
    assert code in password_policy_violations(password)


def test_contains_username():
    assert "contains_username" in password_policy_violations("xMario.Rossi1!", "mario.rossi")
    # Username troppo corti non vengono considerati.
    assert password_policy_violations("Str0ng!pw", "pw") == []
