"""Admin API: server SMTP per le email di piattaforma.

Prefisso: /admin/smtp. La password SMTP e' di sola scrittura: GET espone
solo ``password_present``.
"""

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_admin_role
from src.auth.password_setup import normalize_email, platform_name
from src.data.audit import record_admin_action
from src.data.engine import get_async_session_maker
from src.data.models import User
from src.notifications import email_templates
from src.notifications.mailer import EmailSendError, send_email
from src.notifications.smtp_settings import (
    EMAIL_LANGUAGES,
    SECURITY_MODES,
    get_smtp_config,
    get_smtp_settings_public,
    record_test_result,
    upsert_smtp_settings,
)

logger = logging.getLogger("aion.api.admin_smtp")
router = APIRouter(prefix="/admin/smtp", tags=["admin_smtp"])


def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


class SmtpSettingsBody(BaseModel):
    enabled: bool = True
    host: str = Field(..., max_length=256)
    port: int = Field(587, ge=1, le=65535)
    security: str = "starttls"
    username: Optional[str] = Field(None, max_length=256)
    # Vuota/assente = mantieni quella salvata.
    password: Optional[str] = Field(None, max_length=1024)
    clear_password: bool = False
    from_address: str = Field(..., max_length=256)
    from_name: Optional[str] = Field(None, max_length=256)
    reply_to: Optional[str] = Field(None, max_length=256)
    email_language: str = "it"


class SmtpTestBody(BaseModel):
    to: Optional[str] = None


@router.get("")
async def get_smtp(
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    return await get_smtp_settings_public(_tenant_id())


@router.put("")
async def put_smtp(
    body: SmtpSettingsBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    security = (body.security or "").strip().lower()
    if security not in SECURITY_MODES:
        raise HTTPException(400, detail={"code": "invalid_security"})
    if body.email_language not in EMAIL_LANGUAGES:
        raise HTTPException(400, detail={"code": "invalid_language"})
    host = (body.host or "").strip()
    if not host or any(c.isspace() for c in host):
        raise HTTPException(400, detail={"code": "invalid_host"})
    from_address = normalize_email(body.from_address)
    if not from_address:
        raise HTTPException(400, detail={"code": "invalid_from_address"})
    reply_to = None
    if (body.reply_to or "").strip():
        reply_to = normalize_email(body.reply_to)
        if not reply_to:
            raise HTTPException(400, detail={"code": "invalid_reply_to"})

    tid = _tenant_id()
    await upsert_smtp_settings(
        tid,
        enabled=body.enabled,
        host=host,
        port=body.port,
        security=security,
        username=body.username,
        password=body.password,
        clear_password=body.clear_password,
        from_address=from_address,
        from_name=body.from_name,
        reply_to=reply_to,
        email_language=body.email_language,
        actor_user_id=auth.user_row_id,
    )
    await record_admin_action(
        tenant_id=tid,
        actor=auth.identifier,
        operation="smtp.update",
        resource_type="smtp_settings",
        resource_id=tid,
        payload={
            "host": host,
            "port": body.port,
            "security": security,
            "enabled": body.enabled,
            "password_changed": bool(body.password) or body.clear_password,
        },
    )
    logger.info("SMTP settings updated by %s", auth.identifier)
    return await get_smtp_settings_public(tid)


@router.post("/test")
async def test_smtp(
    body: SmtpTestBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Invia un'email di prova (default: all'email dell'admin)."""
    tid = _tenant_id()
    to = normalize_email(body.to) if (body.to or "").strip() else None
    if (body.to or "").strip() and not to:
        raise HTTPException(400, detail={"code": "invalid_recipient"})
    if to is None and auth.user_row_id:
        async with get_async_session_maker()() as session:
            me = await session.get(User, auth.user_row_id)
            to = normalize_email(me.email if me else None)
    if not to:
        raise HTTPException(400, detail={"code": "recipient_required"})

    cfg = await get_smtp_config(tid)
    if cfg is None:
        raise HTTPException(409, detail={"code": "smtp_not_configured"})
    subject, text, html = email_templates.render(
        "test", cfg.email_language, {"platform": platform_name()}
    )
    error: Optional[str] = None
    try:
        await send_email(tid, to=to, subject=subject, text=text, html=html, cfg=cfg)
    except EmailSendError as e:
        error = e.code
        logger.warning("SMTP test failed: %s", e)
    await record_test_result(tid, error)
    await record_admin_action(
        tenant_id=tid,
        actor=auth.identifier,
        operation="smtp.test",
        resource_type="smtp_settings",
        resource_id=tid,
        payload={"ok": error is None, "error": error},
    )
    return {"ok": error is None, "error": error, "to": to}
