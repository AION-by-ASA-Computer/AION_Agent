"""Telegram channel configuration stored encrypted in the DB (table ``tg_settings``).

Single source of truth for the channel settings, edited from Admin → Telegram
(``GET/PUT /admin/telegram/settings`` in ``src/api/admin_telegram.py``):

- one row per tenant; the explicitly set fields of ``TelegramSettings`` are kept as
  one JSON document encrypted with ``credential_store`` (the manager token too), so
  nothing is stored in clear and a save is atomic;
- the ``.env`` is never read: unset fields fall back to the code defaults;
- loading refreshes the in-process copy behind ``get_telegram_settings()``; the
  gateway is restarted by the caller (``restart_gateway``) so a save applies live,
  without restarting the API container.

Used by the gateway lifecycle (``src/channels/telegram/__init__.py``) and the admin
API. No aiogram import: this runs even with the channel off.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

from pydantic import ValidationError

from src.channels.telegram.config import (
    ADMIN_FIELDS,
    TelegramSettings,
    set_current_settings,
)

logger = logging.getLogger("aion.telegram.settings")

_TABLE = "tg_settings"


class SettingsValidationError(ValueError):
    """Rejected admin update; ``field`` is the first invalid field (or None)."""

    def __init__(self, field: Optional[str], message: str):
        super().__init__(message)
        self.field = field


def _tenant(tenant_id: Optional[str]) -> str:
    from src.channels.telegram.adapter import default_tenant_id

    return tenant_id or default_tenant_id()


async def _table_exists() -> bool:
    """True once the channel was configured or migrated (new DBs have no table)."""
    from sqlalchemy import inspect

    from src.data.engine import init_engine

    async with init_engine().connect() as conn:
        return await conn.run_sync(lambda c: inspect(c).has_table(_TABLE))


async def _load_stored(tenant_id: str) -> Tuple[Dict[str, Any], Optional[datetime]]:
    """Decrypted stored fields and last update time; ``({}, None)`` when absent.

    A blob that cannot be decrypted (encryption key changed or missing) is logged
    and treated as empty: the channel stays off instead of crashing AION startup.
    """
    from src.channels.telegram.models import TgSettings
    from src.data.engine import get_async_session_maker
    from src.runtime.credential_store import decrypt_value

    if not await _table_exists():
        return {}, None
    async with get_async_session_maker()() as session:
        row = await session.get(TgSettings, tenant_id)
    if row is None or not row.data_encrypted:
        return {}, None
    try:
        data = json.loads(decrypt_value(row.data_encrypted))
    except Exception as e:  # noqa: BLE001 — wrong key, corrupt blob, bad JSON
        logger.error(
            "telegram: stored configuration cannot be decrypted (%s): "
            "channel off until it is saved again from Admin → Telegram",
            type(e).__name__,
        )
        return {}, None
    if not isinstance(data, dict):
        return {}, None
    return data, row.updated_at


def _build(data: Mapping[str, Any]) -> TelegramSettings:
    """Validate stored/merged fields into settings, mapping errors to a field name."""
    try:
        return TelegramSettings.model_validate(dict(data))
    except ValidationError as e:
        err = e.errors()[0] if e.errors() else {}
        loc = err.get("loc") or ()
        field = str(loc[0]) if loc else None
        raise SettingsValidationError(field, err.get("msg") or str(e)) from e


async def load_settings(tenant_id: Optional[str] = None) -> TelegramSettings:
    """Configuration from the DB (code defaults for unset fields), without caching."""
    data, _ = await _load_stored(_tenant(tenant_id))
    try:
        return _build(data)
    except SettingsValidationError as e:
        # Only possible if bounds were tightened after the value was saved.
        logger.error(
            "telegram: stored configuration invalid on field %s: using defaults",
            e.field,
        )
        return TelegramSettings()


async def reload_telegram_settings(tenant_id: Optional[str] = None) -> TelegramSettings:
    """Load from the DB and publish as the in-process copy (``get_telegram_settings``)."""
    settings = await load_settings(tenant_id)
    set_current_settings(settings)
    return settings


def _hint(value: Optional[str]) -> Optional[str]:
    """Last 4 chars of the token, so the admin can recognise it without seeing it."""
    if not value:
        return None
    return f"••••{value[-4:]}" if len(value) >= 4 else "••••"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


async def admin_view(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Configuration for the admin UI: every editable field except the token,
    replaced by ``manager_token_present`` / ``manager_token_hint``."""
    data, updated_at = await _load_stored(_tenant(tenant_id))
    try:
        settings = _build(data)
    except SettingsValidationError:
        settings = TelegramSettings()
    values = {
        name: getattr(settings, name)
        for name in ADMIN_FIELDS
        if name != "manager_token"
    }
    token = settings.manager_token_value
    return {
        "settings": values,
        "manager_token_present": bool(token),
        "manager_token_hint": _hint(token),
        "configured": bool(data),
        "updated_at": _iso(updated_at),
    }


async def save_settings(
    changes: Mapping[str, Any],
    *,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Tuple[TelegramSettings, list[str]]:
    """Apply a partial admin update and persist it encrypted.

    ``changes`` holds only the fields the admin touched: a value sets the field,
    ``None`` resets it to the code default (for ``manager_token``: removes it).
    Keeping the saved token when the UI sends a blank/masked value is the caller's
    job (it simply omits the key). Returns the new settings and the names of the
    fields whose effective value changed (empty = nothing written).

    Side effects: creates the channel tables if missing, writes ``tg_settings`` and
    a ``settings_updated`` audit row (field names only, never values), refreshes
    the in-process copy. Raises ``SettingsValidationError`` on invalid input and
    ``RuntimeError`` if encryption is unavailable.
    """
    from src.channels.telegram.bots import token_encryption_error

    unknown = [k for k in changes if k not in ADMIN_FIELDS]
    if unknown:
        raise SettingsValidationError(unknown[0], "unknown setting")
    reason = token_encryption_error()
    if reason:
        raise RuntimeError(reason)

    tenant_id = _tenant(tenant_id)
    stored, _ = await _load_stored(tenant_id)
    before = _build(stored) if stored else TelegramSettings()

    # Merge: None drops the key so the code default applies again.
    merged = {k: v for k, v in stored.items() if k in TelegramSettings.model_fields}
    for key, value in changes.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    after = _build(merged)

    old, new = before.to_storage(), after.to_storage()
    changed = sorted(k for k in ADMIN_FIELDS if old.get(k) != new.get(k))
    if not changed:
        return before, []

    # Persist only the explicitly set fields, normalised by the model (stripped
    # strings, coerced numbers), so defaults changed in code still apply to the rest.
    payload = {k: new[k] for k in merged if new.get(k) is not None}
    await _write(tenant_id, payload, user_id=user_id, changed=changed)
    set_current_settings(after)
    logger.info("telegram: configuration updated (%s)", ", ".join(changed))
    return after, changed


async def _write(
    tenant_id: str, payload: Dict[str, Any], *, user_id: Optional[str], changed: list
) -> None:
    from src.channels.telegram.models import TgSettings, add_audit, ensure_schema
    from src.data.engine import get_async_session_maker
    from src.runtime.credential_store import encrypt_value

    # The admin is configuring the channel: its tables may not exist yet (new DB).
    await ensure_schema()
    blob = encrypt_value(json.dumps(payload, separators=(",", ":")))
    async with get_async_session_maker()() as session:
        row = await session.get(TgSettings, tenant_id)
        if row is None:
            row = TgSettings(tenant_id=tenant_id)
            session.add(row)
        row.data_encrypted = blob
        row.updated_by_user_id = user_id
        row.updated_at = datetime.now(timezone.utc)
        add_audit(session, "settings_updated", aion_user_id=user_id, keys=changed)
        await session.commit()
