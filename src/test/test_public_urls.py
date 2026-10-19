"""Public URL resolution for SSO redirects (chat-ui / admin-ui)."""

import pytest

from starlette.requests import Request

from src.api.public_urls import (
    admin_base_url,
    chat_base_url,
    oauth_redirect_api_base,
)


@pytest.fixture(autouse=True)
def _clean_url_env(monkeypatch):
    for key in (
        "AION_PUBLIC_ADMIN_URL",
        "AION_ADMIN_UI_URL",
        "AION_CHAT_URL",
        "AION_PUBLIC_CHAT_URL",
        "AION_OAUTH_REDIRECT_BASE_URL",
        "AION_PUBLIC_API_URL",
        "AION_FASTAPI_URL",
        "DOMAIN",
        "LETS_ENCRYPT_EMAIL",
        "CADDY_HTTP_PORT",
    ):
        monkeypatch.delenv(key, raising=False)


def test_prod_ignores_stale_localhost_admin_ui_url(monkeypatch):
    # .env copiato da .env.example in produzione: localhost:3870 non deve vincere
    monkeypatch.setenv("AION_ADMIN_UI_URL", "http://localhost:3870")
    monkeypatch.setenv("AION_PUBLIC_API_URL", "https://cliente.example.com/api")
    assert admin_base_url() == "https://cliente.example.com/admin"


def test_prod_domain_only(monkeypatch):
    monkeypatch.setenv("AION_ADMIN_UI_URL", "http://localhost:3870")
    monkeypatch.setenv("DOMAIN", "cliente.example.com")
    monkeypatch.setenv("LETS_ENCRYPT_EMAIL", "ops@example.com")
    assert admin_base_url() == "https://cliente.example.com/admin"


def test_explicit_public_admin_url_wins(monkeypatch):
    monkeypatch.setenv("AION_PUBLIC_ADMIN_URL", "https://admin.example.com/")
    monkeypatch.setenv("AION_PUBLIC_API_URL", "https://cliente.example.com/api")
    assert admin_base_url() == "https://admin.example.com"


def test_local_dev_uses_admin_ui_port(monkeypatch):
    monkeypatch.setenv("AION_ADMIN_UI_URL", "http://localhost:3870")
    monkeypatch.setenv("AION_PUBLIC_API_URL", "http://localhost:8001")
    assert admin_base_url() == "http://localhost:3870"


def test_internal_docker_host_not_used(monkeypatch):
    monkeypatch.setenv("AION_ADMIN_UI_URL", "http://admin-ui:3870")
    monkeypatch.setenv("AION_PUBLIC_API_URL", "https://cliente.example.com/api")
    assert admin_base_url() == "https://cliente.example.com/admin"


def _request(host_header: str, **fwd: str) -> Request:
    headers = [(b"host", host_header.encode())]
    for name, value in fwd.items():
        headers.append((f"x-forwarded-{name}".encode(), value.encode()))
    return Request({"type": "http", "scheme": "http", "path": "/", "headers": headers})


def test_callback_behind_caddy_ignores_stale_localhost_api_url(monkeypatch):
    # .env di produzione copiato da .env.example: AION_PUBLIC_API_URL=localhost:8001
    monkeypatch.setenv("AION_PUBLIC_API_URL", "http://localhost:8001")
    monkeypatch.setenv("AION_OAUTH_REDIRECT_BASE_URL", "http://localhost:8001")
    req = _request(
        "cliente.example.com",
        host="cliente.example.com",
        proto="https",
        prefix="/api",
    )
    assert oauth_redirect_api_base(req) == "https://cliente.example.com/api"
    assert admin_base_url(req) == "https://cliente.example.com/admin"


def test_callback_explicit_public_url_wins(monkeypatch):
    monkeypatch.setenv("AION_PUBLIC_API_URL", "https://cliente.example.com/api")
    req = _request("altro.example.com", proto="https")
    assert oauth_redirect_api_base(req) == "https://cliente.example.com/api"


def test_callback_domain_beats_stale_localhost(monkeypatch):
    monkeypatch.setenv("AION_PUBLIC_API_URL", "http://localhost:8001")
    monkeypatch.setenv("DOMAIN", "pippo.example.com")
    monkeypatch.setenv("LETS_ENCRYPT_EMAIL", "ops@example.com")
    assert oauth_redirect_api_base() == "https://pippo.example.com/api"


def test_callback_local_dev_keeps_localhost(monkeypatch):
    monkeypatch.setenv("AION_PUBLIC_API_URL", "http://localhost:8001")
    req = _request("localhost:8001")
    assert oauth_redirect_api_base(req) == "http://localhost:8001"


def test_callback_internal_backend_host_not_used(monkeypatch):
    monkeypatch.setenv("AION_PUBLIC_API_URL", "http://localhost:8001")
    req = _request("backend:8001")
    assert oauth_redirect_api_base(req) == "http://localhost:8001"


def test_callback_local_docker_stack_behind_caddy(monkeypatch):
    # Stack Docker locale (DOMAIN=:80): il browser passa da Caddy su http://localhost
    monkeypatch.setenv("AION_PUBLIC_API_URL", "http://localhost:8001")
    monkeypatch.setenv("AION_OAUTH_REDIRECT_BASE_URL", "http://localhost:8001")
    monkeypatch.setenv("DOMAIN", ":80")
    req = _request("localhost", host="localhost", proto="http", prefix="/api")
    assert oauth_redirect_api_base(req) == "http://localhost/api"


def test_return_urls_local_docker_stack_behind_caddy(monkeypatch):
    # .env locale: porte di sviluppo, ma il browser usa Caddy su http://localhost
    monkeypatch.setenv("AION_ADMIN_UI_URL", "http://localhost:3870")
    monkeypatch.setenv("AION_CHAT_URL", "http://localhost:8003")
    monkeypatch.setenv("AION_PUBLIC_CHAT_URL", "http://localhost:8003")
    monkeypatch.setenv("AION_PUBLIC_API_URL", "http://localhost:8001")
    monkeypatch.setenv("DOMAIN", ":80")
    req = _request("localhost", host="localhost", proto="http", prefix="/api")
    assert chat_base_url(req) == "http://localhost"
    assert admin_base_url(req) == "http://localhost/admin"


def test_return_urls_local_dev_without_caddy(monkeypatch):
    monkeypatch.setenv("AION_ADMIN_UI_URL", "http://localhost:3870")
    monkeypatch.setenv("AION_PUBLIC_CHAT_URL", "http://localhost:8003")
    monkeypatch.setenv("AION_PUBLIC_API_URL", "http://localhost:8001")
    req = _request("localhost:8001")
    assert chat_base_url(req) == "http://localhost:8003"
    assert admin_base_url(req) == "http://localhost:3870"
