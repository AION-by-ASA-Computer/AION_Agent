"""
Per-user MCP credential store (AES-256-GCM) + async resolution of ${AION_USER_*} env values.

Env:
  AION_CREDENTIAL_ENCRYPTION_KEY — hex-encoded 32-byte key (recommended in production)
  AION_MCP_USER_CREDENTIALS — "1" to enable DB-backed credential resolution
"""
from __future__ import annotations

import base64
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select

from ..data.engine import get_async_session_maker
from ..data.ids import new_uuid7_str
from ..data.models import UserMcpCredential

logger = logging.getLogger("aion.credential_store")

_USER_CREDENTIAL_RE = re.compile(r"^\$\{(AION_USER_[A-Z0-9_]+)__([A-Z0-9_]+)\}$")
_USER_CREDENTIAL_SIMPLE_RE = re.compile(r"^\$\{(AION_USER_[A-Z0-9_]+)\}$")

# Legacy ↔ canonical keys (email MCP migration); lookup tries all aliases.
_CREDENTIAL_KEY_ALIASES: Dict[str, tuple[str, ...]] = {
    "EMAIL_USER": ("IMAP_USER", "SMTP_USER"),
    "EMAIL_PASSWORD": ("IMAP_PASSWORD", "SMTP_PASSWORD"),
    "IMAP_USER": ("EMAIL_USER",),
    "IMAP_PASSWORD": ("EMAIL_PASSWORD",),
    "SMTP_USER": ("EMAIL_USER", "IMAP_USER"),
    "SMTP_PASSWORD": ("EMAIL_PASSWORD", "IMAP_PASSWORD"),
}


def _server_slug_from_env_prefix(env_prefix: str) -> str:
    """AION_USER_EMAIL_MCP_SERVER → email-mcp-server (inverso di _slug_env_prefix)."""
    if not env_prefix.startswith("AION_USER_"):
        return ""
    return env_prefix[len("AION_USER_") :].lower().replace("_", "-")


def user_credentials_enabled() -> bool:
    return os.getenv("AION_MCP_USER_CREDENTIALS", "0").lower() in ("1", "true", "yes")


def _get_encryption_key() -> bytes:
    raw = (os.getenv("AION_CREDENTIAL_ENCRYPTION_KEY") or "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
        except ValueError:
            logger.warning("AION_CREDENTIAL_ENCRYPTION_KEY non è hex valido — uso chiave dev")
            key = b""
        if len(key) in (16, 24, 32):
            return key
        logger.warning(
            "AION_CREDENTIAL_ENCRYPTION_KEY deve essere 16/24/32 byte in hex — uso chiave dev"
        )
    logger.warning(
        "AION_CREDENTIAL_ENCRYPTION_KEY non configurata — uso chiave di sviluppo insicura. "
        "Configurare in produzione."
    )
    return b"aion-dev-insecure-key-0000000000"  # 32 byte


def encrypt_value(plaintext: str) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        logger.warning("cryptography non installata — credenziali salvate in base64 (DEV ONLY)")
        return base64.b64encode(plaintext.encode("utf-8")).decode("ascii")

    key = _get_encryption_key()
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    blob = nonce + ct
    return base64.b64encode(blob).decode("ascii")


def decrypt_value(ciphertext_b64: str) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return base64.b64decode(ciphertext_b64.encode("ascii")).decode("utf-8")

    key = _get_encryption_key()
    blob = base64.b64decode(ciphertext_b64.encode("ascii"))
    if len(blob) < 13:
        return base64.b64decode(ciphertext_b64.encode("ascii")).decode("utf-8")
    nonce = blob[:12]
    ct = blob[12:]
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
    except Exception:
        return base64.b64decode(ciphertext_b64.encode("ascii")).decode("utf-8")


async def set_credential(
    user_id: str,
    server_slug: str,
    key: str,
    value: str,
    *,
    tenant_id: str = "default",
    display_hint: Optional[str] = None,
    expires_at: Optional[datetime] = None,
) -> None:
    encrypted = encrypt_value(value)
    async with get_async_session_maker()() as session:
        existing = (
            await session.execute(
                select(UserMcpCredential).where(
                    UserMcpCredential.user_id == user_id,
                    UserMcpCredential.tenant_id == tenant_id,
                    UserMcpCredential.server_slug == server_slug,
                    UserMcpCredential.credential_key == key,
                )
            )
        ).scalars().first()
        now = datetime.now(timezone.utc)
        if existing:
            existing.value_encrypted = encrypted
            existing.display_hint = display_hint
            existing.expires_at = expires_at
            existing.updated_at = now
        else:
            session.add(
                UserMcpCredential(
                    id=new_uuid7_str(),
                    user_id=user_id,
                    tenant_id=tenant_id,
                    server_slug=server_slug,
                    credential_key=key,
                    value_encrypted=encrypted,
                    display_hint=display_hint,
                    expires_at=expires_at,
                )
            )
        await session.commit()


async def _get_credential_row(
    user_id: str,
    server_slug: str,
    key: str,
    *,
    tenant_id: str = "default",
):
    async with get_async_session_maker()() as session:
        return (
            await session.execute(
                select(UserMcpCredential).where(
                    UserMcpCredential.user_id == user_id,
                    UserMcpCredential.tenant_id == tenant_id,
                    UserMcpCredential.server_slug == server_slug,
                    UserMcpCredential.credential_key == key,
                )
            )
        ).scalars().first()


def credential_key_aliases(key: str) -> tuple[str, ...]:
    """All DB keys to try when resolving a logical credential key (incl. legacy aliases)."""
    return _credential_lookup_keys(key)


def _credential_lookup_keys(key: str) -> tuple[str, ...]:
    k = (key or "").strip()
    if not k:
        return ()
    aliases = _CREDENTIAL_KEY_ALIASES.get(k, ())
    return (k,) + aliases


async def get_credential(
    user_id: str,
    server_slug: str,
    key: str,
    *,
    tenant_id: str = "default",
) -> Optional[str]:
    now = datetime.now(timezone.utc)
    for lookup_key in _credential_lookup_keys(key):
        row = await _get_credential_row(user_id, server_slug, lookup_key, tenant_id=tenant_id)
        if not row:
            continue
        if row.expires_at:
            exp = row.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                logger.info(
                    "Credenziale scaduta: user=%s server=%s key=%s",
                    user_id,
                    server_slug,
                    lookup_key,
                )
                continue
        if lookup_key != key:
            logger.info(
                "Credenziale risolta via alias: richiesta=%s trovata=%s server=%s",
                key,
                lookup_key,
                server_slug,
            )
        return decrypt_value(row.value_encrypted)
    return None


async def list_credentials_hints(
    user_id: str,
    server_slug: str,
    *,
    tenant_id: str = "default",
) -> List[Dict[str, Any]]:
    async with get_async_session_maker()() as session:
        rows = (
            await session.execute(
                select(UserMcpCredential).where(
                    UserMcpCredential.user_id == user_id,
                    UserMcpCredential.tenant_id == tenant_id,
                    UserMcpCredential.server_slug == server_slug,
                )
            )
        ).scalars().all()
    now = datetime.now(timezone.utc)
    res = []
    for r in rows:
        is_expired = False
        if r.expires_at:
            exp = r.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            is_expired = exp < now
        res.append({
            "key": r.credential_key,
            "display_hint": r.display_hint,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "is_expired": is_expired,
        })
    return res


async def delete_credential(
    user_id: str,
    server_slug: str,
    key: str,
    *,
    tenant_id: str = "default",
) -> bool:
    async with get_async_session_maker()() as session:
        result = await session.execute(
            delete(UserMcpCredential).where(
                UserMcpCredential.user_id == user_id,
                UserMcpCredential.tenant_id == tenant_id,
                UserMcpCredential.server_slug == server_slug,
                UserMcpCredential.credential_key == key,
            )
        )
        await session.commit()
    return (result.rowcount or 0) > 0


async def get_all_credentials_for_server(
    user_id: str,
    server_slug: str,
    *,
    tenant_id: str = "default",
) -> Dict[str, str]:
    async with get_async_session_maker()() as session:
        rows = (
            await session.execute(
                select(UserMcpCredential).where(
                    UserMcpCredential.user_id == user_id,
                    UserMcpCredential.tenant_id == tenant_id,
                    UserMcpCredential.server_slug == server_slug,
                )
            )
        ).scalars().all()
    result: Dict[str, str] = {}
    now = datetime.now(timezone.utc)
    for r in rows:
        if r.expires_at:
            exp = r.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                continue
        result[r.credential_key] = decrypt_value(r.value_encrypted)
    return result


async def resolve_user_credential_string(
    obj: str,
    *,
    user_id: str,
    tenant_id: str,
    server_slug: str,
) -> str:
    """Sostituisce un valore stringa se è interamente un placeholder ${AION_USER_*}."""
    if not user_id or not user_credentials_enabled():
        return obj

    m = _USER_CREDENTIAL_RE.match(obj)
    if m:
        full_prefix = m.group(1)
        cred_key = m.group(2)
        # Prefer explicit server_slug (spawn context); else hyphenated slug from env prefix.
        lookup_slugs: list[str] = []
        if server_slug:
            lookup_slugs.append(server_slug)
        from_prefix = _server_slug_from_env_prefix(full_prefix)
        if from_prefix and from_prefix not in lookup_slugs:
            lookup_slugs.append(from_prefix)
        legacy_underscore = full_prefix[len("AION_USER_") :].lower()
        if legacy_underscore and legacy_underscore not in lookup_slugs:
            lookup_slugs.append(legacy_underscore)
        for slug in lookup_slugs:
            val = await get_credential(user_id, slug, cred_key, tenant_id=tenant_id)
            if val is not None:
                return val
        env_name = f"{full_prefix}__{cred_key}"
        return os.environ.get(env_name, obj)

    m2 = _USER_CREDENTIAL_SIMPLE_RE.match(obj)
    if m2 and server_slug:
        cred_key = m2.group(1)[len("AION_USER_") :]
        val = await get_credential(user_id, server_slug, cred_key, tenant_id=tenant_id)
        if val is not None:
            return val
        return os.environ.get(m2.group(1), obj)

    if isinstance(obj, str) and "${AION_USER_" in obj:
        logger.warning(
            "Credenziale MCP non risolta (user=%s server=%s): compila Le mie integrazioni",
            user_id,
            server_slug,
        )
        return ""

    return obj


async def resolve_mcp_env_for_user(
    env: Optional[Dict[str, Any]],
    *,
    user_id: str,
    tenant_id: str,
    server_slug: str,
) -> Dict[str, Any]:
    if not env:
        return {}
    out: Dict[str, Any] = {}
    for k, v in env.items():
        if isinstance(v, str):
            out[k] = await resolve_user_credential_string(
                v, user_id=user_id, tenant_id=tenant_id, server_slug=server_slug
            )
        else:
            out[k] = v
    return out
