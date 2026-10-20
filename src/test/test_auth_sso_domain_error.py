"""Errore SSO per account fuori dai domini consentiti: codice dedicato, mai i domini nell'URL."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import auth_sso
from src.auth.sso import id_token as id_token_mod

ALLOWED = ["secret-corp.example", "Other-Corp.example"]


class _Key:
    key = "k"


class _Jwks:
    def get_signing_key_from_jwt(self, _tok):
        return _Key()


def _verify(monkeypatch, provider, payload):
    monkeypatch.setattr(id_token_mod, "get_jwks_client", lambda _u: _Jwks())
    monkeypatch.setattr(id_token_mod.jwt, "decode", lambda *a, **k: payload)
    cfg = {
        "provider": provider,
        "client_id": "cid",
        "directory_tenant_id": "tid-1",
        "allowed_domains": ALLOWED,
    }
    return id_token_mod.verify_id_token("tok", cfg, "n1")


def test_microsoft_domain_rejected(monkeypatch):
    payload = {"nonce": "n1", "tid": "tid-1", "preferred_username": "a@evil.example"}
    with pytest.raises(ValueError, match="domain_not_allowed"):
        _verify(monkeypatch, "microsoft", payload)


def test_microsoft_domain_case_insensitive(monkeypatch):
    payload = {"nonce": "n1", "tid": "tid-1", "preferred_username": "a@SECRET-corp.example"}
    assert _verify(monkeypatch, "microsoft", payload)["nonce"] == "n1"


def test_google_domain_rejected(monkeypatch):
    payload = {"nonce": "n1", "email_verified": True, "hd": "evil.example"}
    with pytest.raises(ValueError, match="domain_not_allowed"):
        _verify(monkeypatch, "google", payload)


@pytest.mark.parametrize(
    "purpose,expected_prefix",
    [
        ("login", "http://chat.test/login?error="),
        ("link", "http://chat.test/?sso_link_error="),
        ("admin_login", "http://admin.test/login?error="),
    ],
)
def test_callback_redirects_without_leaking_domains(monkeypatch, purpose, expected_prefix):
    async def fake_handle_callback(**_kw):
        return {
            "provider_config": {"provider": "microsoft", "allowed_domains": ALLOWED},
            "id_token": "t",
            "nonce": "n",
            "purpose": purpose,
        }

    def fake_verify(**_kw):
        raise ValueError("domain_not_allowed")

    monkeypatch.setattr(auth_sso, "handle_callback", fake_handle_callback)
    monkeypatch.setattr(auth_sso, "verify_id_token", fake_verify)
    monkeypatch.setattr(auth_sso, "chat_base_url", lambda _r: "http://chat.test")
    monkeypatch.setattr(auth_sso, "admin_base_url", lambda _r: "http://admin.test")

    app = FastAPI()
    app.include_router(auth_sso.router)
    res = TestClient(app).get(
        "/auth/sso/callback?code=c&state=s", follow_redirects=False
    )
    loc = res.headers["location"]
    assert loc == expected_prefix + "sso_domain_not_allowed"
    assert not any(d.lower() in loc.lower() for d in ALLOWED)


def test_account_domain_from_claims():
    from src.auth.sso.config_service import account_domain_from_claims as f

    assert f("microsoft", {"preferred_username": "A@Corp.Example"}) == "corp.example"
    assert f("microsoft", {"preferred_username": "a@t.onmicrosoft.com"}) == "t.onmicrosoft.com"
    assert f("microsoft", {}) is None
    assert f("google", {"hd": "Corp.Example"}) == "corp.example"
    assert f("google", {"email": "a@gmail.com"}) is None
