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

    Env values pointing at localhost (e.g. ``AION_PUBLIC_API_URL=http://localhost:8001``
    left over from ``.env.example``) only win when the request did not come through
    Caddy, so both the production domain and the local Docker stack on
    ``http://localhost`` advertise the URL the browser actually uses.
    """
    candidates = []
    for key, suffix in (
        ("AION_OAUTH_REDIRECT_BASE_URL", ""),
        ("AION_PUBLIC_API_URL", ""),
        ("AION_CHAT_URL", "/api"),
    ):
        val = (os.getenv(key) or "").strip().rstrip("/")
        if _is_absolute_http_url(val):
            candidates.append(f"{val}{suffix}")

    for val in candidates:
        if not _is_loopback_host_url(val):
            return val

    from_request = ""
    if request is not None:
        fwd_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        fwd_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        host = fwd_host or request.headers.get("host", "").split(",")[0].strip()
        scheme = fwd_proto or request.url.scheme
        fwd_prefix = (request.headers.get("x-forwarded-prefix") or "").strip()
        prefix = fwd_prefix or "/api"
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        if host and not host.startswith("backend:"):
            from_request = f"{scheme}://{host}{prefix.rstrip('/')}"
            # X-Forwarded-Prefix is set only by Caddy (/api): the request URL is
            # exactly what the browser sees, also for the local stack on localhost.
            if fwd_prefix or not _is_loopback_host_url(from_request):
                return from_request

    domain_base = _domain_base_url()
    if domain_base:
        return f"{domain_base}/api"

    if candidates:
        return candidates[0]
    if from_request:
        return from_request

    caddy_port = (os.getenv("CADDY_HTTP_PORT") or "80").strip() or "80"
    return f"http://localhost:{caddy_port}/api"


def _domain_base_url() -> str:
    """``https://<DOMAIN>`` from the Docker ``DOMAIN`` var, or "" when unset/local (``:80``)."""
    domain = (os.getenv("DOMAIN") or "").strip()
    for scheme_prefix in ("https://", "http://"):
        if domain.startswith(scheme_prefix):
            domain = domain[len(scheme_prefix) :]
    host = domain.strip("/")
    if not host or host.startswith(":"):
        return ""
    scheme = "https" if (os.getenv("LETS_ENCRYPT_EMAIL") or "").strip() else "http"
    return f"{scheme}://{host}"


def _caddy_origin(request: Optional[Request]) -> str:
    """Browser origin (``scheme://host``) when the request came through Caddy, else "".

    Caddy is the only hop that sets ``X-Forwarded-Prefix`` (/api); that origin is what
    the browser uses, also for the local Docker stack on ``http://localhost``.
    """
    if request is None or not (request.headers.get("x-forwarded-prefix") or "").strip():
        return ""
    fwd_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    fwd_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    host = fwd_host or request.headers.get("host", "").split(",")[0].strip()
    if not host or host.startswith("backend:"):
        return ""
    return f"{fwd_proto or request.url.scheme}://{host}"


def chat_base_url(request: Optional[Request] = None) -> str:
    """
    Browser-facing chat-ui base URL for OAuth return redirects.
    """
    explicit = (os.getenv("AION_CHAT_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(explicit) and not _is_loopback_host_url(explicit):
        return explicit

    public_chat = (os.getenv("AION_PUBLIC_CHAT_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(public_chat) and not _is_loopback_host_url(public_chat):
        return public_chat

    origin = _caddy_origin(request)
    if origin:
        return origin

    api_base = oauth_redirect_api_base(request)
    if _is_absolute_http_url(api_base) and not _is_loopback_host_url(api_base):
        low = api_base.rstrip("/").lower()
        if low.endswith("/api"):
            return api_base.rstrip("/")[:-4]
        return api_base.rstrip("/")

    # Loopback AION_PUBLIC_CHAT_URL (local dev) only after a real public API base,
    # so a stale localhost default cannot shadow the customer domain.
    if _is_absolute_http_url(public_chat):
        return public_chat

    if request is not None:
        fwd_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        fwd_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        host = fwd_host or request.headers.get("host", "").split(",")[0].strip()
        scheme = fwd_proto or request.url.scheme
        if host and not host.startswith("backend:"):
            return f"{scheme}://{host}".rstrip("/")

    domain_base = _domain_base_url()
    if domain_base:
        return domain_base

    if _is_absolute_http_url(explicit):
        return explicit
    return "http://localhost:8003"


def admin_base_url(request: Optional[Request] = None) -> str:
    """
    Browser-facing admin-ui base URL (redirect finale del login SSO admin).

    1. ``AION_PUBLIC_ADMIN_URL`` se assoluto;
    2. layout Docker/Caddy: se la chat ha una base pubblica (non loopback) o la
       richiesta arriva da Caddy (anche lo stack locale su ``http://localhost``),
       stesso dominio sotto ``/admin``;
    3. ``AION_ADMIN_UI_URL`` solo se loopback (dev: admin-ui su porta propria).
       Viene dopo il dominio pubblico, così un ``localhost:3870`` rimasto nel
       ``.env`` (copiato da ``.env.example``) non manda il browser in produzione
       su localhost. In Docker install.sh lo imposta all'host interno
       ``admin-ui:3870``, non raggiungibile dal browser;
    4. fallback: base della chat + ``/admin``.
    """
    explicit = (os.getenv("AION_PUBLIC_ADMIN_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(explicit):
        return explicit
    chat = chat_base_url(request).rstrip("/")
    if _caddy_origin(request) or (
        _is_absolute_http_url(chat) and not _is_loopback_host_url(chat)
    ):
        return f"{chat}/admin"
    dev = (os.getenv("AION_ADMIN_UI_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(dev) and _is_loopback_host_url(dev):
        return dev
    return f"{chat}/admin"
