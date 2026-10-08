"""SSO Admin API."""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.auth_login import ChatAuthIdentity, require_admin_role
from src.auth.sso.config_service import (
    admin_list_providers,
    delete_provider,
    enable_provider,
    upsert_provider,
)
from src.auth.sso.providers import get_descriptor

router = APIRouter(prefix="/admin/sso/providers", tags=["admin_sso"])

def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()

@router.get("")
async def list_configured_providers(
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> List[Dict[str, Any]]:
    return await admin_list_providers(_tenant_id())


@router.get("/redirect-uri")
async def get_redirect_uri(
    request: Request,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, str]:
    """Redirect URI effettivo usato dal backend: e' quello da registrare sull'IdP.

    Il pannello admin non puo' dedurlo da ``window.location`` (dietro Caddy
    l'API e' sotto ``/api``; in dev gira su un'altra porta).
    """
    from src.api.auth_sso import _get_redirect_uri

    return {"redirect_uri": _get_redirect_uri(request)}


class UpsertProviderBody(BaseModel):
    client_id: str
    client_secret: Optional[str] = None
    directory_tenant_id: Optional[str] = None
    allowed_domains: Optional[List[str]] = None
    auto_provision: bool = True
    default_roles: Optional[List[str]] = None


@router.put("/{provider}")
async def put_provider(
    provider: str,
    body: UpsertProviderBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    descriptor = get_descriptor(provider)
    if not descriptor:
        raise HTTPException(400, detail=f"Provider {provider} non supportato")

    try:
        await upsert_provider(
            tenant_id=_tenant_id(),
            provider=provider,
            client_id=body.client_id,
            client_secret=body.client_secret,
            directory_tenant_id=body.directory_tenant_id,
            allowed_domains=body.allowed_domains,
            auto_provision=body.auto_provision,
            default_roles=body.default_roles,
        )
    except Exception as e:
        raise HTTPException(400, detail=str(e))
    return {"ok": True}

@router.post("/{provider}/validate/start")
async def start_provider_validation(
    request: Request,
    provider: str,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    from src.auth.sso.flow import build_authorize_url
    from src.api.auth_sso import _get_redirect_uri
    # Fix 0.1: usa get_provider(require_enabled=False) — la validazione precede l'abilitazione.
    # Fix 0.2: user_id è sempre auth.user_row_id (mai dalla query string).
    try:
        url = await build_authorize_url(
            provider=provider,
            purpose="admin_validate",
            return_to="/",
            redirect_uri=_get_redirect_uri(request),
            tenant_id=_tenant_id(),
            user_id=auth.user_row_id,
        )
        return {"ok": True, "authorize_url": url}
    except Exception as e:
        raise HTTPException(400, detail=str(e))


class EnableProviderBody(BaseModel):
    enabled: bool


@router.post("/{provider}/enable")
async def toggle_provider(
    provider: str,
    body: EnableProviderBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    # ``auth_settings.login_mode`` e' la fonte di verita': abilitare/disabilitare
    # a mano un provider lo desincronizzerebbe (login SSO rotto o link verso il
    # provider sbagliato). Si cambia solo da PUT /admin/auth/login-mode.
    from src.auth.sso.login_mode import get_login_settings

    login_mode = (await get_login_settings(_tenant_id())).get("login_mode")
    if body.enabled != (login_mode == provider):
        raise HTTPException(409, detail={"code": "use_login_mode"})
    try:
        success = await enable_provider(_tenant_id(), provider, body.enabled)
        if not success:
            raise HTTPException(404, detail="Provider not found")
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return {"ok": True, "enabled": body.enabled}


@router.delete("/{provider}")
async def remove_provider(
    provider: str,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    from src.auth.sso.login_mode import get_login_settings

    if (await get_login_settings(_tenant_id())).get("login_mode") == provider:
        # Cancellare il provider attivo chiuderebbe fuori tutti gli utenti SSO.
        raise HTTPException(409, detail={"code": "provider_in_use"})
    await delete_provider(_tenant_id(), provider)
    return {"ok": True}
