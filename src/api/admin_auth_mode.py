"""Admin API: gestione login_mode e pannello migrazione SSO.

Prefisso: /admin/auth  — §3.2 del piano di migrazione.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from src.api.auth_login import ChatAuthIdentity, require_admin_role
from src.auth.sso.login_mode import (
    _check_migration_completion,
    _invalidate_cache,
    confirmed_identity_exists,
    generate_temp_passwords,
    get_login_settings,
    pending_users_count,
)
from src.data.engine import get_async_session_maker
from src.data.models import AuthSettings, User, UserSsoIdentity

logger = logging.getLogger("aion.api.admin_auth_mode")
router = APIRouter(prefix="/admin/auth", tags=["admin_auth"])


def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


# ---------------------------------------------------------------------------
# GET /admin/auth/login-mode
# ---------------------------------------------------------------------------

@router.get("/login-mode")
async def get_login_mode(
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Restituisce le impostazioni di login e lo stato della migrazione."""
    tenant = _tenant_id()
    settings = await get_login_settings(tenant)
    provider = settings.get("sso_provider")

    result: Dict[str, Any] = {
        "login_mode": settings["login_mode"],
        "sso_origin": settings["sso_origin"],
        "sso_migration_active": (
            settings["sso_origin"] == "migration"
            and not settings.get("migration_completed_at")
        ),
        "migration_started_at": settings.get("migration_started_at"),
        "migration_completed_at": settings.get("migration_completed_at"),
        "clear_password_on_link": settings["clear_password_on_link"],
    }

    if provider:
        async with get_async_session_maker()() as session:
            # Migrati = identita' confermata nella migrazione corrente: quelle
            # rimaste da una migrazione precedente non contano.
            migrated_q = select(func.count()).select_from(User).where(
                User.tenant_id == tenant,
                User.sso_migration_exempt == False,  # noqa: E712
                confirmed_identity_exists(
                    tenant, provider, settings.get("migration_started_at")
                ),
            )
            migrated = (await session.execute(migrated_q)).scalar_one()

            exempt_q = select(func.count()).select_from(User).where(
                User.tenant_id == tenant,
                User.sso_migration_exempt == True,  # noqa: E712
            )
            exempt = (await session.execute(exempt_q)).scalar_one()

        pending = await pending_users_count(tenant, provider)
        # Con clear_password_on_link i migrati non hanno piu' password: il totale
        # e' migrati + in attesa (non "utenti con password").
        total = migrated + pending

        # Auto-completamento se la migrazione è terminata ma non è stata registrata
        if result["sso_migration_active"] and pending == 0:
            await _check_migration_completion(tenant, provider)
            settings = await get_login_settings(tenant)
            result["sso_migration_active"] = False
            result["migration_completed_at"] = settings.get("migration_completed_at")

        result["total"] = total
        result["migrated"] = migrated
        result["pending"] = pending
        result["exempt"] = exempt

    return result


# ---------------------------------------------------------------------------
# GET /admin/auth/login-mode/simulate
# ---------------------------------------------------------------------------

@router.get("/login-mode/simulate")
async def simulate_login_mode_change(
    mode: str = Query(..., regex="^(password|microsoft|google)$"),
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Simula il cambio di modalità per identificare gli utenti che riceveranno una password temporanea."""
    tenant = _tenant_id()
    settings = await get_login_settings(tenant)
    current_mode = settings.get("login_mode", "password")

    users_affected = []

    async with get_async_session_maker()() as session:
        if mode != "password" and current_mode in ("microsoft", "google") and current_mode != mode:
            # Cambio da SSO a SSO
            users_without_pw = (
                await session.execute(
                    select(User).where(
                        User.tenant_id == tenant,
                        User.password_hash.is_(None),
                        User.sso_migration_exempt == False,
                        User.id != auth.user_row_id,
                    ).where(
                        ~(
                            select(UserSsoIdentity.id)
                            .where(
                                UserSsoIdentity.user_id == User.id,
                                UserSsoIdentity.tenant_id == tenant,
                                UserSsoIdentity.provider == mode,
                            )
                            .correlate(User)
                            .exists()
                        )
                    )
                )
            ).scalars().all()
        elif mode == "password" and current_mode != "password":
            # Cambio da SSO a password
            users_without_pw = (
                await session.execute(
                    select(User).where(
                        User.tenant_id == tenant,
                        User.password_hash.is_(None),
                        User.sso_migration_exempt == False,
                    )
                )
            ).scalars().all()
        else:
            users_without_pw = []

        for u in users_without_pw:
            users_affected.append({
                "id": u.id,
                "identifier": u.identifier,
                "email": u.email,
                "display_name": u.display_name,
            })

    return {"affected_users": users_affected}


# ---------------------------------------------------------------------------
# PUT /admin/auth/login-mode
# ---------------------------------------------------------------------------

class SetLoginModeBody(BaseModel):
    mode: str  # "password" | "microsoft" | "google"


@router.put("/login-mode")
async def put_login_mode(
    body: SetLoginModeBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Imposta la modalità di login. Vedi §3.2."""
    if not auth.user_row_id:
        raise HTTPException(401, detail="Token utente richiesto")

    from src.auth.sso.login_mode import set_login_mode

    try:
        result = await set_login_mode(
            tenant_id=_tenant_id(),
            mode=body.mode,
            actor_user_id=auth.user_row_id,
        )
    except ValueError as e:
        code = str(e)
        status = 409 if code in (
            "sso_revalidation_required",
            "sso_admin_not_linked",
            "migration_in_progress",
            "provider_not_configured",
        ) else 400
        raise HTTPException(status, detail={"code": code})

    return result


# ---------------------------------------------------------------------------
# GET /admin/auth/sso-migration/users
# ---------------------------------------------------------------------------

@router.get("/sso-migration/users")
async def list_migration_users(
    status: str = Query("pending", regex="^(pending|migrated|exempt|no_access)$"),
    q: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Elenco utenti per stato di migrazione."""
    tenant = _tenant_id()
    settings = await get_login_settings(tenant)
    provider = settings.get("sso_provider")
    since = settings.get("migration_started_at")

    async with get_async_session_maker()() as session:
        if status == "exempt":
            stmt = select(User).where(
                User.tenant_id == tenant,
                User.sso_migration_exempt == True,  # noqa: E712
            )
        elif status == "migrated" and provider:
            stmt = select(User).where(
                User.tenant_id == tenant,
                User.sso_migration_exempt == False,  # noqa: E712
                confirmed_identity_exists(tenant, provider, since),
            )
        elif status == "no_access" and provider:
            # Senza password e senza identita' sul provider attivo: non possono
            # entrare in nessun modo finche' non ricevono una password temporanea
            # (es. dopo uno scollegamento).
            stmt = (
                select(User)
                .where(
                    User.tenant_id == tenant,
                    User.password_hash.is_(None),
                    User.sso_migration_exempt == False,  # noqa: E712
                )
                .where(
                    ~(
                        select(UserSsoIdentity.id)
                        .where(
                            UserSsoIdentity.user_id == User.id,
                            UserSsoIdentity.tenant_id == tenant,
                            UserSsoIdentity.provider == provider,
                        )
                        .correlate(User)
                        .exists()
                    )
                )
            )
        else:  # pending
            if provider:
                stmt = (
                    select(User)
                    .where(
                        User.tenant_id == tenant,
                        User.password_hash.is_not(None),
                        User.sso_migration_exempt == False,  # noqa: E712
                    )
                    .where(~confirmed_identity_exists(tenant, provider, since))
                )
            else:
                stmt = select(User).where(
                    User.tenant_id == tenant,
                    User.password_hash.is_not(None),
                )

        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                (User.identifier.ilike(like)) | (User.email.ilike(like))
            )

        total_count = (
            await session.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar_one()

        stmt = stmt.order_by(User.identifier.asc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()

        users_out = []
        for u in rows:
            entry: Dict[str, Any] = {
                "id": u.id,
                "identifier": u.identifier,
                "email": u.email,
                "display_name": u.display_name,
                "last_active_at": u.last_active_at,
                "created_at": u.created_at,
                "sso_migration_exempt": u.sso_migration_exempt,
            }
            # Informazioni password temporanea per utenti in attesa
            if status == "pending":
                has_temp = u.temp_password_expires_at is not None
                entry["has_temp_password"] = has_temp
                entry["temp_password_expires_at"] = u.temp_password_expires_at

            if status == "migrated" and provider:
                identity = (
                    await session.execute(
                        select(UserSsoIdentity).where(
                            UserSsoIdentity.user_id == u.id,
                            UserSsoIdentity.provider == provider,
                        )
                    )
                ).scalars().first()
                if identity:
                    entry["identity_id"] = identity.id
                    entry["sso_email"] = identity.email
                    entry["linked_at"] = identity.created_at

            users_out.append(entry)

    return {
        "users": users_out,
        "total": total_count,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# POST /admin/auth/sso-migration/users/{id}/exempt
# ---------------------------------------------------------------------------

class ExemptBody(BaseModel):
    exempt: bool


@router.post("/sso-migration/users/{user_id}/exempt")
async def set_user_exempt(
    user_id: str,
    body: ExemptBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Esonera o reintegra un utente nel conteggio migrazione."""
    tenant = _tenant_id()
    async with get_async_session_maker()() as session:
        user = await session.get(User, user_id)
        if not user or user.tenant_id != tenant:
            raise HTTPException(404, detail="Utente non trovato")
        user.sso_migration_exempt = body.exempt
        await session.commit()

    _invalidate_cache(tenant)

    # Controlla se la migrazione è completata
    settings = await get_login_settings(tenant)
    provider = settings.get("sso_provider")
    if provider:
        await _check_migration_completion(tenant, provider)

    return {"ok": True, "user_id": user_id, "exempt": body.exempt}


# ---------------------------------------------------------------------------
# POST /admin/auth/temp-passwords
# ---------------------------------------------------------------------------

class TempPasswordsBody(BaseModel):
    user_ids: List[str]


@router.post("/temp-passwords")
async def admin_generate_temp_passwords(
    body: TempPasswordsBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Genera (o rigenera) password temporanee per gli utenti indicati.

    Le password in chiaro compaiono solo in questa risposta.
    """
    tenant = _tenant_id()
    settings = await get_login_settings(tenant)
    provider = settings.get("sso_provider") or ""

    try:
        results = await generate_temp_passwords(tenant, body.user_ids, provider)
    except ValueError as e:
        code = str(e)
        raise HTTPException(409, detail={"code": code})

    return {"temp_passwords": results}


# ---------------------------------------------------------------------------
# DELETE /admin/users/{id}/sso-identities/{identity_id}
# ---------------------------------------------------------------------------

@router.delete("/users/{user_id}/sso-identities/{identity_id}")
async def unlink_sso_identity(
    user_id: str,
    identity_id: str,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Scollega un'identità SSO da un utente."""
    tenant = _tenant_id()
    async with get_async_session_maker()() as session:
        user = await session.get(User, user_id)
        if not user or user.tenant_id != tenant:
            raise HTTPException(404, detail="Utente non trovato")

        identity = await session.get(UserSsoIdentity, identity_id)
        if not identity or identity.user_id != user_id:
            raise HTTPException(404, detail="Identità non trovata")

        await session.delete(identity)
        await session.commit()

    _invalidate_cache(tenant)
    # Avviso se l'utente non ha più password (non potrà più accedere)
    needs_temp = not user.password_hash
    return {
        "ok": True,
        "user_id": user_id,
        "identity_id": identity_id,
        "user_has_no_password": needs_temp,
    }


# ---------------------------------------------------------------------------
# 2FA TOTP (solo login con password)
# ---------------------------------------------------------------------------

class SetTwoFactorBody(BaseModel):
    required: bool


@router.get("/2fa")
async def get_two_factor(
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    from src.auth.mfa.totp import force_disabled, two_factor_effective

    tid = _tenant_id()
    settings = await get_login_settings(tid)
    async with get_async_session_maker()() as session:
        password_users = (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.tenant_id == tid, User.password_hash.is_not(None))
            )
        ).scalar_one()
        enrolled_users = (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.tenant_id == tid,
                    User.password_hash.is_not(None),
                    User.totp_enabled_at.is_not(None),
                )
            )
        ).scalar_one()
    return {
        "required": bool(settings.get("totp_required")),
        "effective": await two_factor_effective(tid),
        "available": settings.get("login_mode") == "password",
        "force_disabled": force_disabled(),
        "enrolled_users": enrolled_users,
        "password_users": password_users,
    }


@router.put("/2fa")
async def put_two_factor(
    body: SetTwoFactorBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    from datetime import datetime, timezone

    tid = _tenant_id()
    settings = await get_login_settings(tid)
    if body.required and settings.get("login_mode") != "password":
        raise HTTPException(409, detail={"code": "sso_active"})
    async with get_async_session_maker()() as session:
        row = await session.get(AuthSettings, tid)
        if row is None:
            row = AuthSettings(tenant_id=tid, login_mode="password")
            session.add(row)
        if bool(row.totp_required) != body.required:
            row.totp_required = body.required
            row.totp_required_changed_at = datetime.now(timezone.utc)
        row.updated_by_user_id = auth.user_row_id
        await session.commit()
    _invalidate_cache(tid)
    logger.info("2FA required=%s set by %s", body.required, auth.identifier)
    return await get_two_factor(auth)


@router.delete("/users/{user_id}/2fa")
async def reset_user_two_factor(
    user_id: str,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    from src.auth.mfa.totp import reset_user_totp

    async with get_async_session_maker()() as session:
        user = await session.get(User, user_id)
        if not user or user.tenant_id != _tenant_id():
            raise HTTPException(404, detail="User not found")
    await reset_user_totp(user_id)
    logger.info("2FA reset for user %s by %s", user_id, auth.identifier)
    return {"status": "ok", "user_id": user_id, "totp_enabled": False}
