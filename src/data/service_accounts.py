"""Service accounts: non-human ``users`` rows (``account_type='service'``).

A service account is the identity an integration (N8N, scripts, external
systems) uses to call AION. It is a regular ``users`` row so that every part of
the runtime keyed by ``users.id`` / ``users.identifier`` works unchanged
(conversation ownership, profile access, project membership, memory scope, MCP
credentials, ``api_keys.user_id``). What sets it apart:

* the identifier always starts with :data:`SERVICE_PREFIX` and never contains
  ``@``, so it cannot collide with SSO identifiers (emails) or human usernames;
* it has no password, email, roles, SSO identity or 2FA and cannot log in:
  it authenticates only with API keys created by an admin
  (``/admin/service-accounts/{id}/keys``);
* it can be disabled reversibly (``users.disabled_at``): its keys are kept but
  rejected by ``src/api/auth/api_key.authenticate_api_key``;
* long-term memory extraction is off unless the admin enables it
  (``metadata["service"]["ltm_enabled"]``, read by :func:`service_ltm_enabled`).

Used by ``src/api/admin_service_accounts.py`` (admin endpoints), by the auth
layer to block logins, and by ``src/memory/ltm_orchestrator.py``.
See ``docs/security/service-accounts.md``.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .engine import get_async_session_maker
from .models import User
from .user_password import UserAlreadyExistsError, _insert_user

ACCOUNT_TYPE_HUMAN = "human"
ACCOUNT_TYPE_SERVICE = "service"

# Reserved identifier prefix: human accounts may not use it (enforced in
# ``POST /admin/users``), so ``svc-…`` always means "service account".
SERVICE_PREFIX = "svc-"
# Slug after the prefix: lowercase, no ``@`` (SSO identifiers are emails) and
# only characters that ``sanitize_user_id`` keeps unchanged, so the identifier
# stored in ``conversations.user_id`` is exactly ``users.identifier``.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,60}$")

# Upper bound on the key lifetime an admin can allow for a service account.
# Keys must always expire (agreed policy): rotation stays explicit.
MAX_KEY_TTL_DAYS = 365

_META_KEY = "service"

# ``service_ltm_enabled`` runs on every chat turn: cache the answer briefly so
# the post-turn hook does not hit the DB each time. Admin updates call
# :func:`invalidate_ltm_cache` so a change applies immediately in-process.
_LTM_CACHE_TTL_SEC = 30.0
_LTM_CACHE: Dict[str, tuple[float, Optional[bool]]] = {}


class InvalidServiceSlugError(ValueError):
    """The requested slug does not match :data:`SLUG_RE`."""


def is_service(user: Optional[User]) -> bool:
    """True when ``user`` is a service account (``None`` → False)."""
    return bool(
        user is not None and getattr(user, "account_type", None) == ACCOUNT_TYPE_SERVICE
    )


def is_reserved_identifier(identifier: Optional[str]) -> bool:
    """True when a *human* account would use the service-account prefix."""
    return (identifier or "").strip().lower().startswith(SERVICE_PREFIX)


def identifier_for_slug(slug: str) -> str:
    """Build ``svc-<slug>`` after validating the slug.

    Raises :class:`InvalidServiceSlugError` for anything outside
    :data:`SLUG_RE`. A slug that already carries the prefix is accepted too
    (``svc-foo`` → ``svc-foo``), which keeps the admin form forgiving.
    """
    s = (slug or "").strip().lower()
    if s.startswith(SERVICE_PREFIX):
        s = s[len(SERVICE_PREFIX) :]
    if not SLUG_RE.match(s):
        raise InvalidServiceSlugError(slug)
    return SERVICE_PREFIX + s


def service_meta(user: User) -> Dict[str, Any]:
    """Return ``metadata["service"]`` with defaults (never raises on bad JSON)."""
    try:
        meta = json.loads(user.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}
    svc = meta.get(_META_KEY) if isinstance(meta, dict) else None
    svc = svc if isinstance(svc, dict) else {}
    return {
        "description": svc.get("description") or "",
        "ltm_enabled": bool(svc.get("ltm_enabled", False)),
        "created_by": svc.get("created_by"),
    }


def set_service_meta(user: User, **changes: Any) -> None:
    """Merge ``changes`` into ``metadata["service"]`` keeping other metadata keys."""
    try:
        meta = json.loads(user.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    svc = meta.get(_META_KEY) if isinstance(meta.get(_META_KEY), dict) else {}
    svc.update({k: v for k, v in changes.items()})
    meta[_META_KEY] = svc
    user.metadata_json = json.dumps(meta)


async def create_service_account(
    *,
    tenant_id: str,
    slug: str,
    display_name: Optional[str],
    description: Optional[str],
    ltm_enabled: bool,
    max_api_keys: int,
    api_key_max_ttl_days: int,
    created_by: Optional[str],
) -> str:
    """Insert a service account and return its ``users.id``.

    Reuses ``_insert_user`` for the (tenant, identifier) uniqueness check, so a
    clash raises ``UserAlreadyExistsError``. Then marks the row as a service
    account: API keys enabled (keys are created by admins only), exempt from
    the SSO migration count, no password/email/roles.
    """
    identifier = identifier_for_slug(slug)
    uid = await _insert_user(
        tenant_id=tenant_id,
        identifier=identifier,
        password_hash=None,
        display_name=(display_name or "").strip() or identifier,
        email=None,
        roles=[],
        must_change_password=False,
        session_maker=None,
    )
    async with get_async_session_maker()() as session:
        u = await session.get(User, uid)
        assert u is not None  # just inserted
        u.account_type = ACCOUNT_TYPE_SERVICE
        u.can_create_api_keys = True
        u.max_api_keys = max_api_keys
        u.api_key_max_ttl_days = min(api_key_max_ttl_days, MAX_KEY_TTL_DAYS)
        # Never "pending" in an SSO migration: it has nothing to link.
        u.sso_migration_exempt = True
        set_service_meta(
            u,
            description=(description or "").strip(),
            ltm_enabled=bool(ltm_enabled),
            created_by=created_by,
        )
        await session.commit()
    invalidate_ltm_cache(identifier)
    return uid


async def get_service_account(session: AsyncSession, account_id: str) -> Optional[User]:
    """Load a user by id, returning ``None`` unless it is a service account."""
    u = await session.get(User, account_id)
    return u if is_service(u) else None


async def list_service_accounts(session: AsyncSession, tenant_id: str) -> list[User]:
    """All service accounts of the tenant, newest first."""
    q = (
        select(User)
        .where(User.tenant_id == tenant_id, User.account_type == ACCOUNT_TYPE_SERVICE)
        .order_by(User.created_at.desc())
    )
    return list((await session.execute(q)).scalars().all())


def set_disabled(user: User, disabled: bool) -> bool:
    """Enable or disable the account; returns True when the state changed."""
    if disabled and user.disabled_at is None:
        user.disabled_at = datetime.now(timezone.utc)
        return True
    if not disabled and user.disabled_at is not None:
        user.disabled_at = None
        return True
    return False


def invalidate_ltm_cache(identifier: Optional[str] = None) -> None:
    """Drop the cached LTM flag for one identifier (or all of them)."""
    if identifier is None:
        _LTM_CACHE.clear()
    else:
        _LTM_CACHE.pop(identifier, None)


async def service_ltm_enabled(identifier: Optional[str]) -> Optional[bool]:
    """LTM switch for the agent ``user_id`` of a turn.

    Returns ``None`` for human (or unknown) identities, meaning "no override,
    keep the global behaviour"; for service accounts returns the admin's
    ``ltm_enabled`` choice (default False). Cheap pre-check on the prefix: only
    ``svc-…`` identifiers ever touch the DB, and results are cached for
    :data:`_LTM_CACHE_TTL_SEC`. Never raises: on DB errors service accounts
    fall back to "disabled" (the safe choice for automation traffic).
    """
    ident = (identifier or "").strip()
    if not is_reserved_identifier(ident):
        return None
    now = time.monotonic()
    cached = _LTM_CACHE.get(ident)
    if cached and cached[0] > now:
        return cached[1]
    tenant_id = os.getenv("AION_DEFAULT_TENANT_ID", "default")
    try:
        async with get_async_session_maker()() as session:
            u = (
                await session.execute(
                    select(User).where(
                        User.tenant_id == tenant_id, User.identifier == ident
                    )
                )
            ).scalar_one_or_none()
        value: Optional[bool] = (
            service_meta(u)["ltm_enabled"] if is_service(u) else None
        )
    except Exception:
        value = False
    _LTM_CACHE[ident] = (now + _LTM_CACHE_TTL_SEC, value)
    return value


__all__ = [
    "ACCOUNT_TYPE_HUMAN",
    "ACCOUNT_TYPE_SERVICE",
    "InvalidServiceSlugError",
    "MAX_KEY_TTL_DAYS",
    "SERVICE_PREFIX",
    "UserAlreadyExistsError",
    "create_service_account",
    "get_service_account",
    "identifier_for_slug",
    "invalidate_ltm_cache",
    "is_reserved_identifier",
    "is_service",
    "list_service_accounts",
    "service_ltm_enabled",
    "service_meta",
    "set_disabled",
    "set_service_meta",
]
