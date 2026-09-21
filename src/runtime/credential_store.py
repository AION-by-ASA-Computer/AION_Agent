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


class CredentialDecryptionError(RuntimeError):
    """La credenziale cifrata non è decifrabile con la chiave corrente."""


_DEV_ENVS = {"dev", "development", "local", "test", "testing"}

_KEY_HELP = (
    "Impostare AION_CREDENTIAL_ENCRYPTION_KEY con 16/24/32 byte in esadecimale "
    "(es. `openssl rand -hex 32`)."
)


def _is_dev_env() -> bool:
    return (os.getenv("AION_ENV") or "dev").strip().lower() in _DEV_ENVS


def _get_encryption_key() -> bytes:
    raw = (os.getenv("AION_CREDENTIAL_ENCRYPTION_KEY") or "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
        except ValueError:
            key = b""
            reason = "AION_CREDENTIAL_ENCRYPTION_KEY non è hex valido"
        else:
            if len(key) in (16, 24, 32):
                return key
            reason = (
                "AION_CREDENTIAL_ENCRYPTION_KEY deve essere 16/24/32 byte in hex "
                f"(ricevuti {len(key)})"
            )
    else:
        reason = "AION_CREDENTIAL_ENCRYPTION_KEY non configurata"

    if not _is_dev_env():
        logger.error("%s — configurazione non valida. %s", reason, _KEY_HELP)
        raise CredentialDecryptionError(f"{reason}. {_KEY_HELP}")

    logger.warning(
        "%s — uso chiave di sviluppo insicura (AION_ENV=%s). %s",
        reason,
        os.getenv("AION_ENV") or "dev",
        _KEY_HELP,
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


def _as_legacy_plaintext(blob: bytes) -> Optional[str]:
    """Blob salvato in chiaro (base64 puro, pre-AES-GCM): utf-8 valido o None."""
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return None


def decrypt_value(ciphertext_b64: str) -> str:
    """Decifra una credenziale salvata da :func:`encrypt_value`.

    Solleva :class:`CredentialDecryptionError` quando il dato è cifrato ma la
    chiave corrente non corrisponde: il fallback base64 resta valido solo per i
    blob legacy salvati in chiaro.
    """
    try:
        blob = base64.b64decode(ciphertext_b64.encode("ascii"))
    except Exception as exc:  # noqa: BLE001 — dato corrotto o non base64
        raise CredentialDecryptionError(
            "credenziale non decodificabile: il valore salvato non è base64 valido"
        ) from exc

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        legacy = _as_legacy_plaintext(blob)
        if legacy is not None:
            return legacy
        raise CredentialDecryptionError(
            "credenziale cifrata ma il pacchetto `cryptography` non è installato"
        )

    # Troppo corto per essere nonce(12) + tag: blob legacy in chiaro.
    if len(blob) < 13:
        legacy = _as_legacy_plaintext(blob)
        if legacy is not None:
            return legacy
        raise CredentialDecryptionError(
            "credenziale non decodificabile (blob corrotto)"
        )

    nonce, ct = blob[:12], blob[12:]
    try:
        return AESGCM(_get_encryption_key()).decrypt(nonce, ct, None).decode("utf-8")
    except CredentialDecryptionError:
        raise
    except Exception as exc:  # noqa: BLE001 — InvalidTag o chiave errata
        legacy = _as_legacy_plaintext(blob)
        if legacy is not None:
            # Valore storico salvato in chiaro con base64: nessuna cifratura da annullare.
            return legacy
        logger.error(
            "Decifratura credenziale fallita (%s): AION_CREDENTIAL_ENCRYPTION_KEY non "
            "corrisponde alla chiave con cui il dato è stato cifrato.",
            type(exc).__name__,
        )
        raise CredentialDecryptionError(
            "AION_CREDENTIAL_ENCRYPTION_KEY non corrisponde alla chiave usata per "
            "cifrare questa credenziale. Ripristinare la chiave precedente nel .env "
            "oppure risalvare la credenziale (provider LLM / credenziali MCP) per "
            "ri-cifrarla con la chiave corrente."
        ) from exc


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
            "OAuth refresh failed: user=%s server=%s reason=%s",
            user_id,
            server_slug,
            exc,
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
        await _delete_oauth_credentials(user_id, server_slug, tenant_id=tenant_id)
        return None

    return await _persist_oauth_tokens(
        user_id, server_slug, token_data, oauth_cfg, tenant_id=tenant_id
    )


def _slug_variants(server_slug: str) -> list[str]:
    """Genera varianti slug (originale, trattini, underscore)."""
    slugs: list[str] = []
    if server_slug:
        s = server_slug.strip()
        if s:
            slugs.append(s)
            s_dash = s.replace("_", "-")
            if s_dash not in slugs:
                slugs.append(s_dash)
            s_under = s.replace("-", "_")
            if s_under not in slugs:
                slugs.append(s_under)
    return slugs


async def _get_server_credential_mode(server_slug: str) -> str:
    """Restituisce la modalità credenziali del server MCP (per_user, org_shared, none)."""
    slug_candidates = _slug_variants(server_slug)
    try:
        async with get_async_session_maker()() as session:
            for s in slug_candidates:
                row = (
                    (
                        await session.execute(
                            select(McpServerConfig.credential_mode).where(
                                McpServerConfig.server_slug == s
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if row:
                    return str(row).strip().lower()
    except Exception as exc:
        logger.debug(
            "Impossibile determinare credential_mode per %s: %s", server_slug, exc
        )
    return "org_shared"


async def get_credential(
    user_id: str,
    server_slug: str,
    key: str,
    *,
    tenant_id: str = "default",
    auto_refresh_oauth: bool = True,
) -> Optional[str]:
    mode = await _get_server_credential_mode(server_slug)

    if mode == "per_user":
        # Per server MCP strettamente personali (es. email personale):
        # cerca ESCLUSIVAMENTE le credenziali configurate dall'utente corrente
        lookup_user_ids = (
            [user_id] if user_id and user_id not in ("default", "org_shared") else []
        )
    else:
        # Per server MCP di organizzazione / condivisi (org_shared):
        # cerca prima override utente (se presente), poi fallback su default e org_shared
        lookup_user_ids = [user_id] if user_id else ["default"]
        for fallback_uid in ("default", "org_shared"):
            if fallback_uid not in lookup_user_ids:
                lookup_user_ids.append(fallback_uid)

    slug_candidates = _slug_variants(server_slug)

    for uid in lookup_user_ids:
        for slug in slug_candidates:
            for lookup_key in _credential_lookup_keys(key):
                row = await _get_credential_row(
                    uid, slug, lookup_key, tenant_id=tenant_id
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
                            uid, slug, tenant_id=tenant_id
                        )
                        if refreshed:
                            return refreshed
                    logger.info(
                        "Credenziale scaduta: user=%s server=%s key=%s",
                        uid,
                        slug,
                        lookup_key,
                    )
                    continue
                if lookup_key != key:
                    logger.info(
                        "Credenziale risolta via alias: richiesta=%s trovata=%s server=%s",
                        key,
                        lookup_key,
                        slug,
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
    """Sostituisce un valore stringa se è un placeholder (${AION_USER_*} o ${KEY}) o corrisponde a una credenziale DB."""
    if not isinstance(obj, str):
        return obj

    effective_uid = user_id or "default"

    m = _USER_CREDENTIAL_RE.match(obj)
    if m:
        full_prefix = m.group(1)
        cred_key = m.group(2)
        lookup_slugs: list[str] = []
        if server_slug:
            lookup_slugs.extend(_slug_variants(server_slug))
        from_prefix = _server_slug_from_env_prefix(full_prefix)
        if from_prefix:
            for s in _slug_variants(from_prefix):
                if s not in lookup_slugs:
                    lookup_slugs.append(s)
        legacy_underscore = full_prefix[len("AION_USER_") :].lower()
        if legacy_underscore:
            for s in _slug_variants(legacy_underscore):
                if s not in lookup_slugs:
                    lookup_slugs.append(s)
        for slug in lookup_slugs:
            val = await get_credential(
                effective_uid, slug, cred_key, tenant_id=tenant_id
            )
            if val is not None:
                return val
        env_name = f"{full_prefix}__{cred_key}"
        val = os.environ.get(env_name)
        if val is not None:
            return val
        return ""

    m2 = _USER_CREDENTIAL_SIMPLE_RE.match(obj)
    if m2 and server_slug:
        cred_key = m2.group(1)[len("AION_USER_") :]
        val = await get_credential(
            effective_uid, server_slug, cred_key, tenant_id=tenant_id
        )
        if val is not None:
            return val
        val = os.environ.get(m2.group(1))
        if val is not None:
            return val
        return ""

    # Gestione placeholder standard ${VAR_NAME} (es. ${EXA_API_KEY} o ${TAVILY_API_KEY})
    if obj.startswith("${") and obj.endswith("}"):
        var_name = obj[2:-1]
        if server_slug:
            val = await get_credential(
                effective_uid, server_slug, var_name, tenant_id=tenant_id
            )
            if val is not None:
                return val
        env_val = os.environ.get(var_name)
        if env_val is not None:
            return env_val
        # Se la variabile d'ambiente non è presente nell'host, svuota il placeholder per non passare '${VAR}' letterale
        return ""

    if isinstance(obj, str) and "${AION_USER_" in obj:
        logger.warning(
            "Credenziale MCP non risolta (user=%s server=%s): compila Le mie integrazioni",
            user_id,
            server_slug,
        )
        return ""

    return obj


def generate_probe_mock_value(var_name: str) -> str:
    """Restituisce un valore fittizio con tipo semantico corretto per il probe admin."""
    k_lower = var_name.lower()

    # 1. Numeri / limiti / timeout / porte
    if "port" in k_lower:
        return "993" if "imap" in k_lower else "465"
    if any(
        x in k_lower
        for x in (
            "rate",
            "limit",
            "max",
            "connection",
            "message",
            "count",
            "timeout",
            "delay",
            "number",
            "size",
            "retry",
            "interval",
            "ttl",
            "capacity",
            "period",
            "batch",
        )
    ):
        return "10"

    # 2. Booleani / flag
    if any(
        x in k_lower
        for x in (
            "ssl",
            "tls",
            "enable",
            "verify",
            "active",
            "watch",
            "bool",
            "debug",
            "secure",
            "allow",
            "reject",
            "starttls",
            "verbose",
            "headless",
        )
    ):
        return "true"

    # 3. Host / URL
    if "url" in k_lower or "uri" in k_lower:
        return "https://example.com"
    if "host" in k_lower or "server" in k_lower:
        return "imap.example.com"

    # 4. Password / secret / chiavi / token
    if any(
        x in k_lower
        for x in (
            "pass",
            "pwd",
            "secret",
            "token",
            "key",
            "auth",
            "api_key",
            "apikey",
        )
    ):
        return "probe_secret_key"

    # 5. User / account / nomi
    if any(
        x in k_lower
        for x in (
            "username",
            "user_name",
            "login",
            "account_name",
            "full_name",
            "author",
            "owner",
        )
    ):
        return "probe_user"

    # 6. Email / indirizzi specifici
    if (
        "address" in k_lower
        or k_lower.endswith("email")
        or "mail_to" in k_lower
        or "mail_from" in k_lower
        or k_lower in ("email", "mail")
        or "recipient" in k_lower
        or "sender" in k_lower
    ):
        return "probe@example.com"

    return "probe_test_val"


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
    is_probe = user_id == "admin-probe" or "probe" in str(user_id).lower()
    for k, v in env.items():
        if isinstance(v, str):
            val = await resolve_user_credential_string(
                v, user_id=user_id, tenant_id=tenant_id, server_slug=server_slug
            )
            # In sessione di probe dell'admin, se un placeholder non è risolto (o è vuoto),
            # iniettiamo un valore mock per consentire al processo MCP di completare l'handshake e list_tools
            if is_probe and (not val or "${AION_USER_" in str(val) or val == v):
                val = generate_probe_mock_value(k)
            out[k] = val
        else:
            out[k] = v
    return out
