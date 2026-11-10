"""Shared JSON views and validation for API keys.

Used by the user endpoints (``src/api/v1/me_api_keys.py``, chat-ui → Settings →
API keys) and by the admin service-account endpoints
(``src/api/admin_service_accounts.py``) so both return the same key shape and
enforce the same rules (allowed scopes, max lifetime, active-key quota).
Never exposes the secret: only the one-time creation response carries it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Optional

from fastapi import HTTPException

from src.api.auth.api_key import scopes_from_json
from src.api.auth.scopes import ALLOWED_USER_SCOPES
from src.data.models import ApiKey, User


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Treat naive datetimes (SQLite) as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    """ISO-8601 string in UTC, or None."""
    v = as_utc(dt)
    return v.isoformat() if v else None


def serialize_key(row: ApiKey, now: datetime) -> dict:
    """Public view of a key row with a derived ``status`` (active/expired/revoked)."""
    expires = as_utc(row.expires_at)
    if row.revoked_at is not None:
        state = "revoked"
    elif expires is None or expires <= now:
        state = "expired"
    else:
        state = "active"
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "scopes": scopes_from_json(row.scopes_json),
        "created_at": iso(row.created_at),
        "expires_at": iso(row.expires_at),
        "last_used_at": iso(row.last_used_at),
        "revoked_at": iso(row.revoked_at),
        "status": state,
    }


def key_policy(user: User, active: int) -> dict:
    """Key policy of the owner as shown to clients (limits + allowed scopes)."""
    return {
        "enabled": bool(user.can_create_api_keys),
        "max_keys": int(user.max_api_keys),
        "active_count": active,
        "max_ttl_days": int(user.api_key_max_ttl_days),
        "allowed_scopes": list(ALLOWED_USER_SCOPES),
    }


def validated_scopes(scopes: Iterable[str]) -> List[str]:
    """Deduplicate and check scopes; 422 ``invalid_scopes`` on unknown ones."""
    out = sorted(set(scopes))
    invalid = [s for s in out if s not in ALLOWED_USER_SCOPES]
    if invalid:
        raise HTTPException(
            422,
            detail={
                "code": "invalid_scopes",
                "scopes": invalid,
                "message": "Invalid scopes",
            },
        )
    return out


def check_new_key_allowed(user: User, *, expires_in_days: int, active: int) -> None:
    """Enforce the owner's policy before creating a key.

    Raises 403 ``api_keys_disabled``, 422 ``invalid_expiration`` (lifetime over
    ``api_key_max_ttl_days``) or 409 ``api_key_quota_exceeded``.
    """
    if not user.can_create_api_keys:
        raise HTTPException(
            403,
            detail={
                "code": "api_keys_disabled",
                "message": "API key creation is not enabled for this user",
            },
        )
    if expires_in_days > user.api_key_max_ttl_days:
        raise HTTPException(
            422,
            detail={
                "code": "invalid_expiration",
                "max_ttl_days": user.api_key_max_ttl_days,
                "message": f"Expiration must be at most {user.api_key_max_ttl_days} days",
            },
        )
    if active >= user.max_api_keys:
        raise HTTPException(
            409,
            detail={
                "code": "api_key_quota_exceeded",
                "max_keys": user.max_api_keys,
                "message": f"Active API key limit reached ({user.max_api_keys})",
            },
        )
