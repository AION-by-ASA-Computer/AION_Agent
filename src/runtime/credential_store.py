"""
Per-user MCP credential store (AES-256-GCM) + async resolution of ${AION_USER_*} env values.

Env:
  AION_CREDENTIAL_ENCRYPTION_KEY — hex-encoded 32-byte key (recommended in production)
  AION_MCP_USER_CREDENTIALS — "1" to enable DB-backed credential resolution
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select

from ..data.engine import get_async_session_maker
from ..data.ids import new_uuid7_str
from ..data.models import McpServerConfig, UserMcpCredential

logger = logging.getLogger("aion.credential_store")

OAUTH_TOKEN_EXPIRY_BUFFER_SECONDS = int(
    os.getenv("AION_OAUTH_TOKEN_EXPIRY_BUFFER_SECONDS", "60")
)

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
            logger.warning(
                "AION_CREDENTIAL_ENCRYPTION_KEY non è hex valido — uso chiave dev"
            )
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
        logger.warning(
            "cryptography non installata — credenziali salvate in base64 (DEV ONLY)"
        )
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
            (
                await session.execute(
                    select(UserMcpCredential).where(
                        UserMcpCredential.user_id == user_id,
                        UserMcpCredential.tenant_id == tenant_id,
                        UserMcpCredential.server_slug == server_slug,
                        UserMcpCredential.credential_key == key,
                    )
                )
            )
            .scalars()
            .first()
        )
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
            (
                await session.execute(
                    select(UserMcpCredential).where(
                        UserMcpCredential.user_id == user_id,
                        UserMcpCredential.tenant_id == tenant_id,
                        UserMcpCredential.server_slug == server_slug,
                        UserMcpCredential.credential_key == key,
                    )
                )
            )
            .scalars()
            .first()
        )


def credential_key_aliases(key: str) -> tuple[str, ...]:
    """All DB keys to try when resolving a logical credential key (incl. legacy aliases)."""
    return _credential_lookup_keys(key)


def _credential_lookup_keys(key: str) -> tuple[str, ...]:
    k = (key or "").strip()
    if not k:
        return ()
    aliases = _CREDENTIAL_KEY_ALIASES.get(k, ())
    return (k,) + aliases


def _normalize_expiry(expires_at: Optional[datetime]) -> Optional[datetime]:
    if not expires_at:
        return None
    if expires_at.tzinfo is None:
        return expires_at.replace(tzinfo=timezone.utc)
    return expires_at


def _credential_is_expired(
    expires_at: Optional[datetime],
    *,
    buffer_seconds: int = OAUTH_TOKEN_EXPIRY_BUFFER_SECONDS,
) -> bool:
    exp = _normalize_expiry(expires_at)
    if not exp:
        return False
    return exp < (datetime.now(timezone.utc) + timedelta(seconds=buffer_seconds))


async def _load_oauth_config_for_server(server_slug: str) -> Dict[str, Any]:
    async with get_async_session_maker()() as session:
        cfg = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug == server_slug
                    )
                )
            )
            .scalars()
            .first()
        )
    if not cfg or not cfg.oauth_config_json:
        return {}
    try:
        return json.loads(cfg.oauth_config_json)
    except Exception:
        return {}


def _enrich_oauth_config_from_discovery(
    server_slug: str, oauth_cfg: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        from src.mcp_connector_catalog import (
            load_mcp_connector_catalog,
            merge_oauth_config,
            oauth_config_from_connector,
            resolve_connector_row_for_mcp_server,
        )
        from src.mcp_credential_discovery import discover_mcp_credentials
        from src.mcp_manager import mcp_manager

        reg_cfg = mcp_manager.get_server_config(server_slug) or {}
        catalog = load_mcp_connector_catalog()
        row = resolve_connector_row_for_mcp_server(server_slug, reg_cfg, catalog)
        oauth_cfg = merge_oauth_config(
            oauth_cfg, oauth_config_from_connector(row), catalog_overrides=True
        )
        if oauth_cfg.get("token_url"):
            return oauth_cfg
        discovered = discover_mcp_credentials(server_slug, reg_cfg)
        if discovered and discovered.remote_auth_type == "oauth2":
            merged = dict(oauth_cfg)
            merged.setdefault(
                "provider",
                discovered.remote_oauth_provider or merged.get("provider") or "generic",
            )
            merged.setdefault(
                "authorization_server",
                discovered.remote_oauth_server or merged.get("authorization_server"),
            )
            merged.setdefault(
                "token_url",
                discovered.remote_oauth_token_url or merged.get("token_url"),
            )
            return merged
    except Exception:
        pass
    return oauth_cfg


async def _delete_oauth_credentials(
    user_id: str,
    server_slug: str,
    *,
    tenant_id: str = "default",
) -> None:
    await delete_credential(user_id, server_slug, "OAUTH_TOKEN", tenant_id=tenant_id)
    await delete_credential(
        user_id, server_slug, "OAUTH_REFRESH_TOKEN", tenant_id=tenant_id
    )


async def _persist_oauth_tokens(
    user_id: str,
    server_slug: str,
    token_data: Dict[str, Any],
    oauth_cfg: Dict[str, Any],
    *,
    tenant_id: str = "default",
) -> str:
    from src.runtime.oauth_token_exchange import token_expires_at

    access_token = str(token_data["access_token"])
    expires_at = token_expires_at(token_data)
    await set_credential(
        user_id,
        server_slug,
        "OAUTH_TOKEN",
        access_token,
        tenant_id=tenant_id,
        display_hint=oauth_cfg.get("provider", "oauth2"),
        expires_at=expires_at,
    )

    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        await set_credential(
            user_id,
            server_slug,
            "OAUTH_REFRESH_TOKEN",
            str(refresh_token),
            tenant_id=tenant_id,
        )

    from src.runtime.mcp_credential_invalidate import invalidate_mcp_credentials_runtime

    await invalidate_mcp_credentials_runtime(user_id, server_slug, tenant_id=tenant_id)
    return access_token


async def persist_oauth_token_response(
    user_id: str,
    server_slug: str,
    token_data: Dict[str, Any],
    oauth_cfg: Dict[str, Any],
    *,
    tenant_id: str = "default",
) -> str:
    """Save OAuth access/refresh tokens and restart MCP workers for the user."""
    return await _persist_oauth_tokens(
        user_id, server_slug, token_data, oauth_cfg, tenant_id=tenant_id
    )


async def refresh_oauth_access_token(
    user_id: str,
    server_slug: str,
    *,
    tenant_id: str = "default",
) -> Optional[str]:
    """Refresh an expired OAuth access token when a refresh token is available."""
    refresh_token = await get_credential(
        user_id,
        server_slug,
        "OAUTH_REFRESH_TOKEN",
        tenant_id=tenant_id,
        auto_refresh_oauth=False,
    )
    if not refresh_token:
        return None

    oauth_cfg = _enrich_oauth_config_from_discovery(
        server_slug, await _load_oauth_config_for_server(server_slug)
    )
    token_url = oauth_cfg.get("token_url")
    if not token_url:
        logger.warning(
            "OAuth refresh skipped: missing token_url user=%s server=%s",
            user_id,
            server_slug,
        )
        return None

    from src.runtime.oauth_token_exchange import (
        OAuthTokenExchangeError,
        exchange_refresh_token,
    )

    try:
        token_data = await exchange_refresh_token(
            token_url,
            refresh_token=refresh_token,
            client_id=oauth_cfg.get("client_id"),
            client_secret=oauth_cfg.get("client_secret"),
        )
    except OAuthTokenExchangeError as exc:
        logger.warning(
            "OAuth refresh failed: user=%s server=%s reason=%s status=%s",
            user_id,
            server_slug,
            exc,
            exc.status_code,
        )
        from src.runtime.mcp_oauth_audit import append_mcp_oauth_audit

        append_mcp_oauth_audit(
            "oauth_refresh_failed",
            {
                "user_id": user_id,
                "server_slug": server_slug,
                "tenant_id": tenant_id,
                "reason": str(exc),
                "status_code": exc.status_code,
            },
        )
        # Elimina le credenziali OAuth solo se il server ha esplicitamente rifiutato
        # il refresh_token come non valido (401 = token revocato/scaduto).
        # Per errori 400 (es. client non registrato per grant refresh_token, errori di
        # configurazione) o errori di rete (None), conserviamo il refresh_token:
        # potrebbe funzionare dopo un re-login che aggiorna il client_id nel DB.
        if exc.status_code == 401:
            logger.info(
                "OAuth refresh: refresh_token revocato o scaduto per user=%s server=%s — "
                "elimino le credenziali OAuth per forzare un nuovo login.",
                user_id,
                server_slug,
            )
            await _delete_oauth_credentials(user_id, server_slug, tenant_id=tenant_id)
        else:
            logger.info(
                "OAuth refresh: errore non definitivo (status=%s) per user=%s server=%s — "
                "conservo il refresh_token per nuovi tentativi.",
                exc.status_code,
                user_id,
                server_slug,
            )
        return None

    return await _persist_oauth_tokens(
        user_id, server_slug, token_data, oauth_cfg, tenant_id=tenant_id
    )


async def get_credential(
    user_id: str,
    server_slug: str,
    key: str,
    *,
    tenant_id: str = "default",
    auto_refresh_oauth: bool = True,
) -> Optional[str]:
    for lookup_key in _credential_lookup_keys(key):
        row = await _get_credential_row(
            user_id, server_slug, lookup_key, tenant_id=tenant_id
        )
        if not row:
            continue
        if _credential_is_expired(row.expires_at):
            if (
                auto_refresh_oauth
                and lookup_key == "OAUTH_TOKEN"
                and key == "OAUTH_TOKEN"
            ):
                refreshed = await refresh_oauth_access_token(
                    user_id, server_slug, tenant_id=tenant_id
                )
                if refreshed:
                    return refreshed
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
            (
                await session.execute(
                    select(UserMcpCredential).where(
                        UserMcpCredential.user_id == user_id,
                        UserMcpCredential.tenant_id == tenant_id,
                        UserMcpCredential.server_slug == server_slug,
                    )
                )
            )
            .scalars()
            .all()
        )
    res = []
    for r in rows:
        is_expired = _credential_is_expired(r.expires_at)
        res.append(
            {
                "key": r.credential_key,
                "display_hint": r.display_hint,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "is_expired": is_expired,
            }
        )
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
            (
                await session.execute(
                    select(UserMcpCredential).where(
                        UserMcpCredential.user_id == user_id,
                        UserMcpCredential.tenant_id == tenant_id,
                        UserMcpCredential.server_slug == server_slug,
                    )
                )
            )
            .scalars()
            .all()
        )
    result: Dict[str, str] = {}
    for r in rows:
        if _credential_is_expired(r.expires_at):
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
