import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from src.data.engine import get_async_session_maker
from src.data.ids import new_uuid7_str
from src.data.models import SsoProvider
from src.runtime.credential_store import (
    CredentialDecryptionError,
    decrypt_value,
    encrypt_value,
)

logger = logging.getLogger("aion.sso.config")


def _row_to_provider_dict(row: SsoProvider) -> Optional[Dict[str, Any]]:
    """Converte una riga SsoProvider in dizionario, decryptando il secret."""
    try:
        secret = None
        if row.client_secret_encrypted:
            secret = decrypt_value(row.client_secret_encrypted)
        return {
            "id": row.id,
            "provider": row.provider,
            "client_id": row.client_id,
            "client_secret": secret,
            "directory_tenant_id": row.directory_tenant_id,
            "allowed_domains": json.loads(row.allowed_domains) if row.allowed_domains else [],
            "auto_provision": row.auto_provision,
            "default_roles": json.loads(row.default_roles) if row.default_roles else ["user"],
            "enabled": row.enabled,
            "validated_at": row.validated_at,
            "validated_by_user_id": row.validated_by_user_id,
        }
    except CredentialDecryptionError:
        logger.error("Failed to decrypt SSO client secret for provider %s.", row.provider)
        return None

# Simple in-memory cache (tenant_id -> (expiry, provider_dict))
_CACHE: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}
CACHE_TTL = 30.0


async def get_active_provider(tenant_id: str = "default") -> Optional[Dict[str, Any]]:
    """Restituisce il provider SSO attivo (enabled=True), con cache di 30s."""
    import time

    now = time.time()
    cached = _CACHE.get(tenant_id)
    if cached and now < cached[0]:
        return cached[1]

    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(SsoProvider).where(
                        SsoProvider.tenant_id == tenant_id, SsoProvider.enabled == True
                    )
                )
            )
            .scalars()
            .first()
        )

    if not row:
        _CACHE[tenant_id] = (now + CACHE_TTL, None)
        return None

    result = _row_to_provider_dict(row)
    _CACHE[tenant_id] = (now + CACHE_TTL, result)
    return result


async def get_provider(
    tenant_id: str,
    provider: str,
    *,
    require_enabled: bool = True,
) -> Optional[Dict[str, Any]]:
    """Restituisce la configurazione di un provider specifico.

    Se ``require_enabled=True`` (default) restituisce None se il provider non
    è abilitato. Con ``require_enabled=False`` restituisce il provider anche
    se non ancora abilitato (usato dal flusso admin_validate, dove la
    validazione precede l'abilitazione).
    """
    async with get_async_session_maker()() as session:
        stmt = select(SsoProvider).where(
            SsoProvider.tenant_id == tenant_id,
            SsoProvider.provider == provider,
        )
        row = (await session.execute(stmt)).scalars().first()

    if not row:
        return None
    if require_enabled and not row.enabled:
        return None
    return _row_to_provider_dict(row)


async def upsert_provider(
    tenant_id: str,
    provider: str,
    client_id: str,
    client_secret: Optional[str] = None,
    directory_tenant_id: Optional[str] = None,
    allowed_domains: Optional[list] = None,
    auto_provision: bool = True,
    default_roles: Optional[list] = None,
) -> None:
    _CACHE.pop(tenant_id, None)

    async with get_async_session_maker()() as session:
        existing = (
            (
                await session.execute(
                    select(SsoProvider).where(
                        SsoProvider.tenant_id == tenant_id,
                        SsoProvider.provider == provider,
                    )
                )
            )
            .scalars()
            .first()
        )

        now = datetime.now(timezone.utc)
        
        roles_str = json.dumps(default_roles or ["user"])
        domains_str = json.dumps(allowed_domains) if allowed_domains else None

        secret_encrypted = None
        if existing and not client_secret:
            secret_encrypted = existing.client_secret_encrypted
        elif client_secret:
            try:
                secret_encrypted = encrypt_value(client_secret)
            except Exception as e:
                raise ValueError(str(e)) from e
        
        # If anything crucial changes, it requires re-validation
        needs_revalidation = False
        if existing:
            if existing.client_id != client_id:
                needs_revalidation = True
            if existing.directory_tenant_id != directory_tenant_id:
                needs_revalidation = True
            if client_secret:
                needs_revalidation = True

        if existing:
            existing.client_id = client_id
            existing.client_secret_encrypted = secret_encrypted
            existing.directory_tenant_id = directory_tenant_id
            existing.allowed_domains = domains_str
            existing.auto_provision = auto_provision
            existing.default_roles = roles_str
            existing.updated_at = now
            if needs_revalidation:
                existing.validated_at = None
                existing.validated_by_user_id = None
                # Se questo e' il provider ATTIVO non lo spegniamo: con
                # login_mode su SSO e provider disabilitato nessuno (admin
                # incluso, senza break-glass) potrebbe piu' accedere. Resta
                # acceso e l'admin deve solo rivalidarlo dal pannello.
                login_active = False
                try:
                    from src.auth.sso.login_mode import get_login_settings

                    login_active = (
                        await get_login_settings(tenant_id)
                    ).get("login_mode") == provider
                except Exception:  # noqa: BLE001
                    login_active = False
                if not login_active:
                    existing.enabled = False
        else:
            session.add(
                SsoProvider(
                    id=new_uuid7_str(),
                    tenant_id=tenant_id,
                    provider=provider,
                    client_id=client_id,
                    client_secret_encrypted=secret_encrypted,
                    directory_tenant_id=directory_tenant_id,
                    allowed_domains=domains_str,
                    auto_provision=auto_provision,
                    default_roles=roles_str,
                    enabled=False,
                )
            )

        # Disable all other providers for this tenant
        if existing and existing.enabled:
            others = (
                (
                    await session.execute(
                        select(SsoProvider).where(
                            SsoProvider.tenant_id == tenant_id,
                            SsoProvider.provider != provider,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for other in others:
                other.enabled = False

        await session.commit()


async def mark_validated(tenant_id: str, provider: str, user_id: str) -> None:
    _CACHE.pop(tenant_id, None)
    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(SsoProvider).where(
                        SsoProvider.tenant_id == tenant_id,
                        SsoProvider.provider == provider,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row:
            row.validated_at = datetime.now(timezone.utc)
            row.validated_by_user_id = user_id
            await session.commit()


async def public_view(tenant_id: str) -> Optional[Dict[str, Any]]:
    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(SsoProvider).where(
                        SsoProvider.tenant_id == tenant_id
                    ).order_by(SsoProvider.updated_at.desc())
                )
            )
            .scalars()
            .first()
        )

    if not row:
        return None

    secret_hint = None
    if row.client_secret_encrypted:
        try:
            val = decrypt_value(row.client_secret_encrypted)
            secret_hint = f"••••{val[-4:]}" if len(val) >= 4 else "••••"
        except CredentialDecryptionError:
            secret_hint = "(error: key mismatch)"

    return {
        "provider": row.provider,
        "client_id": row.client_id,
        "client_secret_hint": secret_hint,
        "directory_tenant_id": row.directory_tenant_id,
        "allowed_domains": json.loads(row.allowed_domains) if row.allowed_domains else [],
        "auto_provision": row.auto_provision,
        "default_roles": json.loads(row.default_roles) if row.default_roles else ["user"],
        "enabled": row.enabled,
        "validated_at": row.validated_at,
    }

async def enable_provider(tenant_id: str, provider: str, enabled: bool) -> bool:
    _CACHE.pop(tenant_id, None)
    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(SsoProvider).where(
                        SsoProvider.tenant_id == tenant_id,
                        SsoProvider.provider == provider,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not row:
            return False
        
        if enabled and not row.validated_at:
            raise ValueError("Provider not validated")

        row.enabled = enabled
        row.updated_at = datetime.now(timezone.utc)
        
        if enabled:
            others = (
                (
                    await session.execute(
                        select(SsoProvider).where(
                            SsoProvider.tenant_id == tenant_id,
                            SsoProvider.provider != provider,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for other in others:
                other.enabled = False

        await session.commit()
        return True

async def delete_provider(tenant_id: str, provider: str) -> None:
    _CACHE.pop(tenant_id, None)
    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(SsoProvider).where(
                        SsoProvider.tenant_id == tenant_id,
                        SsoProvider.provider == provider,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row:
            await session.delete(row)
            await session.commit()

async def admin_list_providers(tenant_id: str) -> List[Dict[str, Any]]:
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(SsoProvider).where(
                        SsoProvider.tenant_id == tenant_id
                    ).order_by(SsoProvider.provider.asc())
                )
            )
            .scalars()
            .all()
        )

    res = []
    for row in rows:
        secret_hint = None
        if row.client_secret_encrypted:
            try:
                val = decrypt_value(row.client_secret_encrypted)
                secret_hint = f"••••{val[-4:]}" if len(val) >= 4 else "••••"
            except CredentialDecryptionError:
                secret_hint = "(error: key mismatch)"

        res.append({
            "provider": row.provider,
            "client_id": row.client_id,
            "client_secret_hint": secret_hint,
            "directory_tenant_id": row.directory_tenant_id,
            "allowed_domains": json.loads(row.allowed_domains) if row.allowed_domains else [],
            "auto_provision": row.auto_provision,
            "default_roles": json.loads(row.default_roles) if row.default_roles else ["user"],
            "enabled": row.enabled,
            "validated_at": row.validated_at,
            "validated_by_user_id": row.validated_by_user_id,
        })
    return res
