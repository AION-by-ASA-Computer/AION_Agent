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
    from src.api.auth_sso import sso_start
    # Riutilizziamo sso_start che ha la logica di pkce, passandogli purpose=admin_validate
    # Questo endpoint risponde JSON { "authorize_url": ... } in modo che l'admin panel possa aprire un popup.
    from src.auth.sso.flow import build_authorize_url
    from src.api.auth_sso import _get_redirect_uri
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
    await delete_provider(_tenant_id(), provider)
    return {"ok": True}
