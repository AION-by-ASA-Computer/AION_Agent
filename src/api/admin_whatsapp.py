"""Admin API del canale WhatsApp (admin-ui → Piattaforma → WhatsApp).

Incluso nel router ``/admin`` (``require_admin_role`` ereditato). Come per
l'SSO: si salvano le credenziali, si verifica il collegamento con Meta e solo
dopo una verifica riuscita si può attivare il canale.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_admin_role
from src.channels.whatsapp import config_service, dispatcher, linking
from src.channels.whatsapp.graph_client import GraphError

router = APIRouter(prefix="/whatsapp", tags=["admin_whatsapp"])


def _tenant_id() -> str:
    return config_service.default_tenant_id()


class WhatsAppConfigBody(BaseModel):
    waba_id: str = Field(..., min_length=1, max_length=64)
    phone_number_id: str = Field(..., min_length=1, max_length=64)
    access_token: Optional[str] = None
    app_secret: Optional[str] = None
    default_profile_slug: Optional[str] = None


class WhatsAppEnableBody(BaseModel):
    enabled: bool


@router.get("")
async def get_whatsapp_config() -> Dict[str, Any]:
    return await config_service.admin_view(_tenant_id())


@router.put("")
async def put_whatsapp_config(body: WhatsAppConfigBody) -> Dict[str, Any]:
    profile = (body.default_profile_slug or "").strip() or None
    if profile:
        from src.agent_profile import profile_manager

        # get_profile e non resolve_profile: quest'ultimo ricade sul default.
        profile_manager.load_all_if_stale()
        if profile_manager.get_profile(profile) is None:
            raise HTTPException(
                400,
                detail={
                    "code": "profile_not_found",
                    "message": f"Profile '{profile}' not found",
                },
            )
    await config_service.upsert_channel(
        _tenant_id(),
        waba_id=body.waba_id,
        phone_number_id=body.phone_number_id,
        access_token=body.access_token,
        app_secret=body.app_secret,
        default_profile_slug=profile,
    )
    return await config_service.admin_view(_tenant_id())


@router.post("/verify-token")
async def regenerate_verify_token() -> Dict[str, str]:
    token = await config_service.regenerate_verify_token(_tenant_id())
    return {"verify_token": token}


def _check(check_id: str, ok: bool, detail: str) -> Dict[str, Any]:
    return {"id": check_id, "ok": ok, "detail": detail}


@router.post("/validate")
async def validate_whatsapp(
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Checklist sul collegamento Meta; imposta ``validated_at`` se tutto ok."""
    tenant_id = _tenant_id()
    config_service.invalidate_cache()
    cfg = await config_service.get_channel(tenant_id)
    if cfg is None or not cfg.configured:
        raise HTTPException(
            409,
            detail={
                "code": "not_configured",
                "message": "Save WABA ID, Phone Number ID, access token and app secret first",
            },
        )

    client = dispatcher.graph_client_factory(cfg.access_token or "")
    checks: List[Dict[str, Any]] = []
    display: Optional[str] = cfg.display_phone_number
    verified_name: Optional[str] = cfg.verified_name

    try:
        info = await client.get_phone_info(cfg.phone_number_id or "")
        display = info.get("display_phone_number") or display
        verified_name = info.get("verified_name") or verified_name
        quality = info.get("quality_rating") or "—"
        checks.append(
            _check(
                "token_phone",
                True,
                f"{verified_name or '—'} · {display or '—'} · quality {quality}",
            )
        )
        platform = str(info.get("platform_type") or "").upper()
        checks.append(
            _check(
                "cloud_api_registered",
                platform == "CLOUD_API",
                platform or "platform_type not returned",
            )
        )
    except GraphError as e:
        checks.append(_check("token_phone", False, str(e)))
        checks.append(_check("cloud_api_registered", False, "skipped"))

    try:
        apps = await client.get_subscribed_apps(cfg.waba_id or "")
        subscribed_now = False
        if not apps:
            subscribed_now = await client.subscribe_app(cfg.waba_id or "")
            apps = (
                await client.get_subscribed_apps(cfg.waba_id or "")
                if subscribed_now
                else []
            )
        names = [
            str((a.get("whatsapp_business_api_data") or {}).get("name") or "")
            for a in apps
        ]
        detail = ", ".join(n for n in names if n) or (
            "subscribed" if apps else "no app subscribed"
        )
        if subscribed_now:
            detail = f"{detail} (subscribed now)"
        checks.append(_check("app_subscribed", bool(apps), detail))
    except GraphError as e:
        checks.append(_check("app_subscribed", False, str(e)))

    checks.append(
        _check(
            "webhook_verified",
            cfg.webhook_verified_at is not None,
            cfg.webhook_verified_at.isoformat()
            if cfg.webhook_verified_at
            else "not verified by Meta yet",
        )
    )

    ok = all(c["ok"] for c in checks)
    if ok:
        await config_service.mark_validated(
            tenant_id,
            auth.user_row_id,
            display_phone_number=display,
            verified_name=verified_name,
        )
    else:
        await config_service.update_phone_info(
            tenant_id, display_phone_number=display, verified_name=verified_name
        )
        first = next(c for c in checks if not c["ok"])
        await config_service.set_last_error(
            tenant_id, f"{first['id']}: {first['detail']}"
        )
    return {
        "ok": ok,
        "checks": checks,
        "channel": await config_service.admin_view(tenant_id),
    }


@router.post("/enable")
async def enable_whatsapp(body: WhatsAppEnableBody) -> Dict[str, Any]:
    try:
        await config_service.set_enabled(_tenant_id(), body.enabled)
    except config_service.ChannelStateError as e:
        raise HTTPException(409, detail={"code": e.code})
    return {"ok": True, "enabled": body.enabled}


@router.get("/identities")
async def list_whatsapp_identities() -> Dict[str, Any]:
    return {"items": await linking.list_identities(_tenant_id())}


@router.delete("/identities/{identity_id}")
async def delete_whatsapp_identity(identity_id: str) -> Dict[str, Any]:
    if not await linking.unlink(_tenant_id(), identity_id=identity_id):
        raise HTTPException(404, detail={"code": "identity_not_found"})
    return {"ok": True}
