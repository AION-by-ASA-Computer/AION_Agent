"""Admin endpoints for service accounts (``/admin/service-accounts``).

Service accounts are non-human ``users`` rows (``account_type='service'``)
used by integrations to call AION with API keys. Only admins manage them and
their keys: the service account itself can never log in or create keys. The
router is included by ``src/api/admin.py`` under the ``/admin`` router, so every
route inherits ``require_admin_role`` (API keys are always refused there).

Data helpers live in ``src/data/service_accounts.py``; key views and policy
checks are shared with ``/v1/me/api-keys`` via ``src/api/auth/api_key_view.py``.
Every mutating call is written to ``audit_log`` (never with secrets).
See ``docs/security/service-accounts.md``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from src.api.auth.api_key_view import (
    check_new_key_allowed,
    iso,
    key_policy,
    serialize_key,
    validated_scopes,
)
from src.api.auth.scopes import Scope
from src.api.auth_login import ChatAuthIdentity, require_admin_role
from src.data import api_keys as api_keys_db
from src.data import service_accounts as svc
from src.data.audit import record_admin_action
from src.data.engine import get_async_session_maker
from src.data.models import ApiKey, User, UserProfileAccess

logger = logging.getLogger("aion.api.admin_service_accounts")

router = APIRouter(prefix="/service-accounts", tags=["admin-service-accounts"])


def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


class ServiceAccountCreate(BaseModel):
    """Body of ``POST /admin/service-accounts``; the identifier becomes ``svc-<slug>``."""

    slug: str = Field(..., min_length=1, max_length=70)
    display_name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = Field(None, max_length=1000)
    # Off by default: automation traffic should not fill long-term memory.
    ltm_enabled: bool = False
    max_api_keys: int = Field(5, ge=1, le=100)
    api_key_max_ttl_days: int = Field(90, ge=1, le=svc.MAX_KEY_TTL_DAYS)


class ServiceAccountUpdate(BaseModel):
    """Body of ``PATCH /admin/service-accounts/{id}``; omitted fields are unchanged."""

    display_name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = Field(None, max_length=1000)
    disabled: Optional[bool] = None
    ltm_enabled: Optional[bool] = None
    max_api_keys: Optional[int] = Field(None, ge=1, le=100)
    api_key_max_ttl_days: Optional[int] = Field(None, ge=1, le=svc.MAX_KEY_TTL_DAYS)


class ServiceKeyCreate(BaseModel):
    """Body of ``POST /admin/service-accounts/{id}/keys``. Expiry is mandatory."""

    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default_factory=lambda: [Scope.CHAT], min_length=1)
    expires_in_days: int = Field(..., ge=1)


def _serialize_account(
    u: User,
    *,
    active_keys: int,
    last_used_at: Optional[datetime],
    profiles: List[str],
) -> Dict[str, Any]:
    """Admin view of a service account (no credentials of any kind)."""
    meta = svc.service_meta(u)
    return {
        "id": u.id,
        "identifier": u.identifier,
        "display_name": u.display_name,
        "description": meta["description"],
        "disabled": u.disabled_at is not None,
        "disabled_at": iso(u.disabled_at),
        "ltm_enabled": meta["ltm_enabled"],
        "max_api_keys": u.max_api_keys,
        "api_key_max_ttl_days": u.api_key_max_ttl_days,
        "active_keys": active_keys,
        "last_used_at": iso(last_used_at),
        "created_at": iso(u.created_at),
        "created_by": meta["created_by"],
        "profiles": profiles,
    }


async def _account_view(session, u: User) -> Dict[str, Any]:
    """Serialize one account loading its key stats and allowed profiles."""
    active = await api_keys_db.count_active(session, u.id)
    last_used = (
        await session.execute(
            select(func.max(ApiKey.last_used_at)).where(ApiKey.user_id == u.id)
        )
    ).scalar()
    profiles = list(
        (
            await session.execute(
                select(UserProfileAccess.profile_slug).where(
                    UserProfileAccess.user_id == u.id
                )
            )
        )
        .scalars()
        .all()
    )
    return _serialize_account(
        u, active_keys=active, last_used_at=last_used, profiles=profiles
    )


async def _load_or_404(session, account_id: str) -> User:
    """Return the service account or 404 (also for human user ids)."""
    u = await svc.get_service_account(session, account_id)
    if u is None or u.tenant_id != _tenant_id():
        raise HTTPException(404, detail={"code": "service_account_not_found"})
    return u


@router.get("")
async def list_service_accounts() -> Dict[str, Any]:
    """List service accounts with active-key count, last key use and profiles."""
    tenant = _tenant_id()
    async with get_async_session_maker()() as session:
        rows = await svc.list_service_accounts(session, tenant)
        ids = [u.id for u in rows]
        active = await api_keys_db.count_active_by_user(session)
        last_used: Dict[str, Any] = {}
        profiles: Dict[str, List[str]] = {}
        if ids:
            # One grouped query each instead of N per-account queries.
            for uid, ts in (
                await session.execute(
                    select(ApiKey.user_id, func.max(ApiKey.last_used_at))
                    .where(ApiKey.user_id.in_(ids))
                    .group_by(ApiKey.user_id)
                )
            ).all():
                last_used[uid] = ts
            for uid, slug in (
                await session.execute(
                    select(UserProfileAccess.user_id, UserProfileAccess.profile_slug)
                    .where(UserProfileAccess.user_id.in_(ids))
                )
            ).all():
                profiles.setdefault(uid, []).append(slug)
    return {
        "items": [
            _serialize_account(
                u,
                active_keys=active.get(u.id, 0),
                last_used_at=last_used.get(u.id),
                profiles=profiles.get(u.id, []),
            )
            for u in rows
        ]
    }


@router.post("", status_code=201)
async def create_service_account(
    body: ServiceAccountCreate,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Create a service account.

    Allowed in SSO mode too (unlike ``POST /admin/users``): the account never
    signs in, so the "accounts are born at first SSO login" rule does not apply.
    """
    tenant = _tenant_id()
    try:
        uid = await svc.create_service_account(
            tenant_id=tenant,
            slug=body.slug,
            display_name=body.display_name,
            description=body.description,
            ltm_enabled=body.ltm_enabled,
            max_api_keys=body.max_api_keys,
            api_key_max_ttl_days=body.api_key_max_ttl_days,
            created_by=auth.identifier,
        )
    except svc.InvalidServiceSlugError:
        raise HTTPException(422, detail={"code": "invalid_service_slug"})
    except svc.UserAlreadyExistsError:
        raise HTTPException(409, detail={"code": "user_exists"})

    async with get_async_session_maker()() as session:
        u = await _load_or_404(session, uid)
        out = await _account_view(session, u)
    await record_admin_action(
        tenant_id=tenant,
        actor=auth.identifier,
        operation="service_account.create",
        resource_type="service_account",
        resource_id=uid,
        payload={"identifier": out["identifier"], "ltm_enabled": body.ltm_enabled},
    )
    return out


@router.patch("/{account_id}")
async def update_service_account(
    account_id: str,
    body: ServiceAccountUpdate,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Update name, description, LTM switch, key limits or the disabled state.

    Lowering the limits applies to new keys only (same as for people); disabling
    keeps the keys but makes authentication reject them until re-enabled.
    """
    tenant = _tenant_id()
    changed: Dict[str, Any] = {}
    toggled: Optional[str] = None
    async with get_async_session_maker()() as session:
        u = await _load_or_404(session, account_id)
        if body.display_name is not None:
            u.display_name = body.display_name.strip() or u.identifier
            changed["display_name"] = u.display_name
        meta_changes: Dict[str, Any] = {}
        if body.description is not None:
            meta_changes["description"] = body.description.strip()
        if body.ltm_enabled is not None:
            meta_changes["ltm_enabled"] = bool(body.ltm_enabled)
        if meta_changes:
            svc.set_service_meta(u, **meta_changes)
            changed.update(meta_changes)
        if body.max_api_keys is not None:
            u.max_api_keys = body.max_api_keys
            changed["max_api_keys"] = body.max_api_keys
        if body.api_key_max_ttl_days is not None:
            u.api_key_max_ttl_days = body.api_key_max_ttl_days
            changed["api_key_max_ttl_days"] = body.api_key_max_ttl_days
        if body.disabled is not None and svc.set_disabled(u, body.disabled):
            toggled = "disable" if body.disabled else "enable"
        await session.commit()
        await session.refresh(u)
        out = await _account_view(session, u)
    # The LTM flag is cached per identifier for a few seconds: apply now.
    svc.invalidate_ltm_cache(u.identifier)

    if changed:
        await record_admin_action(
            tenant_id=tenant,
            actor=auth.identifier,
            operation="service_account.update",
            resource_type="service_account",
            resource_id=account_id,
            payload=changed,
        )
    if toggled:
        await record_admin_action(
            tenant_id=tenant,
            actor=auth.identifier,
            operation=f"service_account.{toggled}",
            resource_type="service_account",
            resource_id=account_id,
            payload={"identifier": u.identifier},
        )
    return out


@router.delete("/{account_id}")
async def delete_service_account(
    account_id: str,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Delete the account and its keys and profile access.

    Reuses ``DELETE /admin/users/{id}`` (same explicit cascade, since SQLite DBs
    patched in place have no FK cascades). Conversations stay, like for people.
    """
    from src.api.admin import delete_user  # lazy: admin.py includes this router

    tenant = _tenant_id()
    async with get_async_session_maker()() as session:
        u = await _load_or_404(session, account_id)
        identifier = u.identifier
    await delete_user(account_id)
    svc.invalidate_ltm_cache(identifier)
    await record_admin_action(
        tenant_id=tenant,
        actor=auth.identifier,
        operation="service_account.delete",
        resource_type="service_account",
        resource_id=account_id,
        payload={"identifier": identifier},
    )
    return {"deleted": True}


@router.get("/{account_id}/keys")
async def list_service_account_keys(account_id: str) -> Dict[str, Any]:
    """Keys of the account (never the secrets) plus its key policy."""
    now = datetime.now(timezone.utc)
    async with get_async_session_maker()() as session:
        u = await _load_or_404(session, account_id)
        rows = await api_keys_db.list_user_keys(session, u.id)
        active = await api_keys_db.count_active(session, u.id)
        policy = key_policy(u, active)
    return {"policy": policy, "keys": [serialize_key(r, now) for r in rows]}


@router.post("/{account_id}/keys", status_code=201)
async def create_service_account_key(
    account_id: str,
    body: ServiceKeyCreate,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Create a key for the account; the full secret is returned only here.

    Same rules as personal keys: allowed scopes, mandatory expiry within the
    account's ``api_key_max_ttl_days``, active-key quota. Allowed while the
    account is disabled (the key just won't authenticate until re-enabled).
    """
    tenant = _tenant_id()
    scopes = validated_scopes(body.scopes)
    async with get_async_session_maker()() as session:
        u = await _load_or_404(session, account_id)
        active = await api_keys_db.count_active(session, u.id)
        check_new_key_allowed(u, expires_in_days=body.expires_in_days, active=active)
        row, full_key = await api_keys_db.create_user_key(
            session,
            u,
            name=body.name.strip(),
            scopes=scopes,
            ttl_days=body.expires_in_days,
        )
        await session.commit()
        out = serialize_key(row, datetime.now(timezone.utc))
    await record_admin_action(
        tenant_id=tenant,
        actor=auth.identifier,
        operation="service_account.key.create",
        resource_type="service_account",
        resource_id=account_id,
        # Prefix only: it identifies the key without allowing its use.
        payload={
            "key_id": out["id"],
            "prefix": out["prefix"],
            "scopes": scopes,
            "expires_at": out["expires_at"],
        },
    )
    return {**out, "key": full_key}


@router.delete("/{account_id}/keys/{key_id}")
async def revoke_service_account_key(
    account_id: str,
    key_id: str,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Revoke (soft) one key of the account; 404 if it belongs to someone else."""
    tenant = _tenant_id()
    async with get_async_session_maker()() as session:
        u = await _load_or_404(session, account_id)
        row = await api_keys_db.revoke_key(session, u.id, key_id)
        if row is None:
            raise HTTPException(404, detail={"code": "api_key_not_found"})
        await session.commit()
        out = serialize_key(row, datetime.now(timezone.utc))
    await record_admin_action(
        tenant_id=tenant,
        actor=auth.identifier,
        operation="service_account.key.revoke",
        resource_type="service_account",
        resource_id=account_id,
        payload={"key_id": key_id, "prefix": out["prefix"]},
    )
    return out
