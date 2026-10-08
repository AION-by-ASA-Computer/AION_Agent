"""Helper for public URL generation (chat-ui and api-base)."""

import os
from typing import Optional
from fastapi import Request

def _is_loopback_host_url(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def _is_absolute_http_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def _public_api_base_url() -> str:
    """Absolute public API base (scheme + host + optional path prefix). Skips relative `/api`."""
    for key in (
        "AION_OAUTH_REDIRECT_BASE_URL",
        "AION_PUBLIC_API_URL",
        "AION_FASTAPI_URL",
    ):
        val = (os.getenv(key) or "").strip().rstrip("/")
        if _is_absolute_http_url(val):
            return val
    return ""


def oauth_redirect_api_base(request: Optional[Request] = None) -> str:
    """
    Browser-facing API base for OAuth callbacks (…/api), not the internal uvicorn URL.
    """
    explicit = (os.getenv("AION_OAUTH_REDIRECT_BASE_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(explicit):
        return explicit

    public = (os.getenv("AION_PUBLIC_API_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(public):
        return public

    chat = (os.getenv("AION_CHAT_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(chat):
        return f"{chat}/api"

    if request is not None:
        fwd_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        fwd_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        host = fwd_host or request.headers.get("host", "").split(",")[0].strip()
        scheme = fwd_proto or request.url.scheme
        prefix = (request.headers.get("x-forwarded-prefix") or "/api").strip() or "/api"
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        if host:
            return f"{scheme}://{host}{prefix.rstrip('/')}"

    domain = (os.getenv("DOMAIN") or "").strip()
    if domain and domain not in (":80", "http://:80"):
        host = domain.lstrip("http://").lstrip("https://").strip("/")
        if host and not host.startswith(":"):
            scheme = (
                "https" if (os.getenv("LETS_ENCRYPT_EMAIL") or "").strip() else "http"
            )
            return f"{scheme}://{host}/api"

    caddy_port = (os.getenv("CADDY_HTTP_PORT") or "80").strip() or "80"
    return f"http://localhost:{caddy_port}/api"


def chat_base_url(request: Optional[Request] = None) -> str:
    """
    Browser-facing chat-ui base URL for OAuth return redirects.
    """
    explicit = (os.getenv("AION_CHAT_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(explicit) and not _is_loopback_host_url(explicit):
        return explicit

    public_chat = (os.getenv("AION_PUBLIC_CHAT_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(public_chat):
        return public_chat

    api_base = oauth_redirect_api_base(request)
    if _is_absolute_http_url(api_base) and not _is_loopback_host_url(api_base):
        low = api_base.rstrip("/").lower()
        if low.endswith("/api"):
            return api_base.rstrip("/")[:-4]
        return api_base.rstrip("/")

    if request is not None:
        fwd_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        fwd_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        host = fwd_host or request.headers.get("host", "").split(",")[0].strip()
        scheme = fwd_proto or request.url.scheme
        if host and not host.startswith("backend:"):
            return f"{scheme}://{host}".rstrip("/")

    domain = (os.getenv("DOMAIN") or "").strip()
    if domain and domain not in (":80", "http://:80"):
        host = domain.lstrip("http://").lstrip("https://").strip("/")
        if host and not host.startswith(":"):
            scheme = (
                "https" if (os.getenv("LETS_ENCRYPT_EMAIL") or "").strip() else "http"
            )
            return f"{scheme}://{host}"

    if _is_absolute_http_url(explicit):
        return explicit
    return "http://localhost:8003"


def admin_base_url(request: Optional[Request] = None) -> str:
    """
    Browser-facing admin-ui base URL (redirect finale del login SSO admin).

    1. ``AION_PUBLIC_ADMIN_URL`` se assoluto;
    2. ``AION_ADMIN_UI_URL`` solo se loopback (dev: admin-ui su porta propria).
       In Docker install.sh lo imposta all'host interno ``admin-ui:3870``, non
       raggiungibile dal browser;
    3. layout Docker/Caddy: stesso dominio della chat sotto ``/admin``.
    """
    explicit = (os.getenv("AION_PUBLIC_ADMIN_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(explicit):
        return explicit
    dev = (os.getenv("AION_ADMIN_UI_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(dev) and _is_loopback_host_url(dev):
        return dev
    return f"{chat_base_url(request).rstrip('/')}/admin"
