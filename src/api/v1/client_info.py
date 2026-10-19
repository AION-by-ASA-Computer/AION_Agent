"""``GET /v1/client/info``: handshake pubblico per i client Enterprise.

Contratto: aion-cowork/docs/enterprise-api-contract.md (``api_version = 1``).
Nessun segreto: solo versione e modalita' di login gia' esposte da ``/auth/status``.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from src.api.auth_login import auth_status
from src.api.public_urls import chat_base_url
from src.version import __version__

router = APIRouter(tags=["v1-client"])

API_VERSION = 1
MIN_CLIENT_VERSION = "1.0.0"


@router.get("/client/info")
async def client_info() -> Dict[str, Any]:
    st = await auth_status()
    try:
        base = (chat_base_url() or "").strip().rstrip("/")
    except Exception:
        base = ""
    return {
        "product": "aion-agent",
        "api_version": API_VERSION,
        "version": __version__,
        "min_client_version": MIN_CLIENT_VERSION,
        "login_mode": st["login_mode"],
        "password_auth_enabled": st["password_auth_enabled"],
        "sso_enabled": st["sso_enabled"],
        "two_factor_required": st["two_factor_required"],
        "token_ttl_seconds": st["token_ttl_seconds"],
        "login_url": f"{base}/login" if base else None,
        "features": {
            "llm_proxy": True,
            "client_bootstrap": True,
            "desktop_login": True,
        },
    }
