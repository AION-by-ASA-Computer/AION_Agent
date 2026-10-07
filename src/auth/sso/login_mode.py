"""Servizio login_mode: fonte di verità per la modalità di accesso SSO.

Implementa §2 del piano di migrazione.
"""

import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, text

from src.data.engine import get_async_session_maker
from src.data.models import AuthSettings, SsoProvider, User, UserSsoIdentity

logger = logging.getLogger("aion.sso.login_mode")

# Cache semplice in memoria (tenant_id → (expiry, settings_dict))
_SETTINGS_CACHE: Dict[str, tuple] = {}
_PENDING_CACHE: Dict[str, tuple] = {}
CACHE_TTL = 15.0  # secondi


def _force_password() -> bool:
    """Break-glass ``AION_SSO_FORCE_PASSWORD=1`` (vedi auth_login.sso_force_password)."""
    return (os.getenv("AION_SSO_FORCE_PASSWORD") or "").strip() == "1"


def _invalidate_cache(tenant_id: str) -> None:
    _SETTINGS_CACHE.pop(tenant_id, None)
    # La cache dei pendenti e' indicizzata "tenant:provider": rimuovi tutte le chiavi del tenant.
    prefix = f"{tenant_id}:"
    for key in [k for k in _PENDING_CACHE if k.startswith(prefix)]:
        _PENDING_CACHE.pop(key, None)


async def is_migration_active(tenant_id: str) -> bool:
    """True se SSO attivo con origin ``migration`` e migrazione non completata.

    Stessa definizione usata da ``/auth/status`` (``sso_migration_active``).
    Mentre e' attiva, un'identita' IdP non collegata NON puo' creare un nuovo
    utente (``sso_not_linked``): deve prima collegarsi dall'account esistente.
    """
    if _force_password():
        return False
    settings = await get_login_settings(tenant_id)
    return (
        settings["login_mode"] != "password"
        and settings["sso_origin"] == "migration"
        and not settings["migration_completed_at"]
    )


async def get_login_settings(tenant_id: str) -> Dict[str, Any]:
    """Restituisce login_mode, provider, origin, started_at, completed_at,
    clear_password_on_link. Cache di 15s."""
    now = time.time()
    cached = _SETTINGS_CACHE.get(tenant_id)
    if cached and now < cached[0]:
        return cached[1]

    async with get_async_session_maker()() as session:
        row = await session.get(AuthSettings, tenant_id)

    if not row:
        result = {
            "login_mode": "password",
            "sso_origin": None,
            "migration_started_at": None,
            "migration_completed_at": None,
            "clear_password_on_link": True,
            "sso_provider": None,
            "totp_required": False,
        }
    else:
        mode = row.login_mode or "password"
        result = {
            "login_mode": mode,
            "sso_origin": row.sso_origin,
            "migration_started_at": row.migration_started_at,
            "migration_completed_at": row.migration_completed_at,
            "clear_password_on_link": bool(row.clear_password_on_link),
            "sso_provider": mode if mode != "password" else None,
            "totp_required": bool(getattr(row, "totp_required", False)),
        }

    _SETTINGS_CACHE[tenant_id] = (now + CACHE_TTL, result)
    return result


async def pending_users_count(tenant_id: str, provider: str) -> int:
    """Conta gli utenti con password che non hanno ancora un'identità SSO
    per il provider attivo e non sono esonerati. Cache di 15s."""
    cache_key = f"{tenant_id}:{provider}"
    now = time.time()
    cached = _PENDING_CACHE.get(cache_key)
    if cached and now < cached[0]:
        return cached[1]

    async with get_async_session_maker()() as session:
        # Utenti con password, non esonerati, senza identità per questo provider
        stmt = (
            select(func.count())
            .select_from(User)
            .where(
                User.tenant_id == tenant_id,
                User.password_hash.is_not(None),
                User.sso_migration_exempt == False,  # noqa: E712
            )
            .where(
                ~(
                    select(UserSsoIdentity.id)
                    .where(
                        UserSsoIdentity.user_id == User.id,
                        UserSsoIdentity.tenant_id == tenant_id,
                        UserSsoIdentity.provider == provider,
                    )
                    .correlate(User)
                    .exists()
                )
            )
        )
        count = (await session.execute(stmt)).scalar_one()

    _PENDING_CACHE[cache_key] = (now + CACHE_TTL, count)
    return count


async def password_login_visible(tenant_id: str) -> bool:
    """Determina se il form di login con password deve essere visibile in chat-ui."""
    settings = await get_login_settings(tenant_id)
    mode = settings["login_mode"]
    origin = settings["sso_origin"]

    if mode == "password" or _force_password():
        return True
    if origin == "first_setup":
        return False
    # origin == "migration" → visibile finché ci sono utenti non migrati
    provider = settings["sso_provider"]
    if not provider:
        return True
    count = await pending_users_count(tenant_id, provider)
    return count > 0


async def user_needs_link(tenant_id: str, user_row_id: str) -> bool:
    """Restituisce True se l'utente deve ancora collegarsi al provider SSO attivo."""
    settings = await get_login_settings(tenant_id)
    mode = settings["login_mode"]
    if mode == "password" or _force_password():
        return False

    provider = settings["sso_provider"]
    if not provider:
        return False

    async with get_async_session_maker()() as session:
        user = await session.get(User, user_row_id)
        if not user:
            return False
        if bool(getattr(user, "sso_migration_exempt", False)):
            return False

        identity = (
            await session.execute(
                select(UserSsoIdentity).where(
                    UserSsoIdentity.tenant_id == tenant_id,
                    UserSsoIdentity.user_id == user_row_id,
                    UserSsoIdentity.provider == provider,
                )
            )
        ).scalars().first()

    return identity is None


async def _check_migration_completion(tenant_id: str, provider: str) -> None:
    """Se pending_users_count arriva a 0, scrive migration_completed_at."""
    # Il conteggio e' in cache 15s: senza invalidazione il collegamento appena
    # avvenuto non verrebbe visto e la migrazione non risulterebbe mai completata.
    _invalidate_cache(tenant_id)
    count = await pending_users_count(tenant_id, provider)
    if count == 0:
        async with get_async_session_maker()() as session:
            row = await session.get(AuthSettings, tenant_id)
            if row and row.sso_origin == "migration" and not row.migration_completed_at:
                row.migration_completed_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info(
                    "SSO migration completed for tenant %s (provider %s)",
                    tenant_id,
                    provider,
                )
        _invalidate_cache(tenant_id)


async def set_login_mode(
    tenant_id: str,
    mode: str,
    *,
    actor_user_id: str,
    provider_validated_at: Optional[datetime] = None,
    revalidation_window_minutes: int = 30,
) -> Dict[str, Any]:
    """Cambia la modalità di login. Vedi §3.2.

    Restituisce il dizionario con le impostazioni aggiornate.
    Può contenere 'temp_passwords' se il cambio richiede password temporanee.
    """
    from src.auth.sso.config_service import enable_provider, get_provider
    from src.data.user_password import hash_password

    if mode not in ("password", "microsoft", "google"):
        raise ValueError("invalid_mode")

    async with get_async_session_maker()() as session:
        now = datetime.now(timezone.utc)

        # Leggi impostazioni correnti
        current_row = await session.get(AuthSettings, tenant_id)
        current_mode = current_row.login_mode if current_row else "password"

        temp_passwords_out: List[Dict] = []

        if mode != "password":
            # Verifica che il provider esista e sia validato
            from src.auth.sso.config_service import get_provider as _gp
            config = await _gp(tenant_id, mode, require_enabled=False)
            if not config:
                raise ValueError("provider_not_configured")
            if not config.get("validated_at"):
                raise ValueError("sso_revalidation_required")

            # Verifica che la validazione sia recente
            validated_at = config["validated_at"]
            if validated_at.tzinfo is None:
                validated_at = validated_at.replace(tzinfo=timezone.utc)
            if (now - validated_at).total_seconds() > revalidation_window_minutes * 60:
                raise ValueError("sso_revalidation_required")

            # Verifica che l'admin che chiama abbia già un'identità per il provider
            actor_identity = (
                await session.execute(
                    select(UserSsoIdentity).where(
                        UserSsoIdentity.tenant_id == tenant_id,
                        UserSsoIdentity.user_id == actor_user_id,
                        UserSsoIdentity.provider == mode,
                    )
                )
            ).scalars().first()
            if not actor_identity:
                raise ValueError("sso_admin_not_linked")

            # Calcola origin
            first_setup_complete = os.getenv("AION_FIRST_SETUP_COMPLETE") == "1"
            if not first_setup_complete:
                sso_origin = "first_setup"
            elif current_mode in ("microsoft", "google") and current_mode != mode:
                # Cambio da SSO a SSO → sempre migration
                sso_origin = "migration"
            else:
                sso_origin = "migration"

            # Blocca se c'è una migrazione in corso (cambio provider)
            if (
                current_mode in ("microsoft", "google")
                and current_mode != mode
                and current_row
                and current_row.sso_origin == "migration"
                and not current_row.migration_completed_at
            ):
                # Conta utenti in attesa sul vecchio provider
                old_pending = await pending_users_count(tenant_id, current_mode)
                if old_pending > 0:
                    raise ValueError("migration_in_progress")

            # Step 4: aggiorna auth_settings
            migration_started = now if sso_origin == "migration" else None
            if current_row and current_mode == mode:
                # Ri-conferma dello stesso provider (es. dopo cambio secret):
                # NON riaprire la migrazione ne' cambiare origin; si riabilita
                # solo il provider (enable_provider, dopo il commit).
                current_row.updated_by_user_id = actor_user_id
                current_row.updated_at = now
            elif current_row:
                current_row.login_mode = mode
                current_row.sso_origin = sso_origin
                current_row.migration_started_at = migration_started
                current_row.migration_completed_at = None
                current_row.updated_by_user_id = actor_user_id
                current_row.updated_at = now
            else:
                session.add(AuthSettings(
                    tenant_id=tenant_id,
                    login_mode=mode,
                    sso_origin=sso_origin,
                    migration_started_at=migration_started,
                    migration_completed_at=None,
                    clear_password_on_link=True,
                    updated_by_user_id=actor_user_id,
                    updated_at=now,
                ))

            # Step 4-bis: cambio da SSO a SSO — genera password temporanee
            # per chi non ha password e non ha identità per il nuovo provider
            if current_mode in ("microsoft", "google") and current_mode != mode:
                ttl_days = int(os.getenv("AION_SSO_TEMP_PASSWORD_TTL_DAYS", "7"))
                temp_expires = now + timedelta(days=ttl_days)

                users_without_pw = (
                    await session.execute(
                        select(User).where(
                            User.tenant_id == tenant_id,
                            User.password_hash.is_(None),
                            User.sso_migration_exempt == False,  # noqa: E712
                            User.id != actor_user_id,
                        ).where(
                            ~(
                                select(UserSsoIdentity.id)
                                .where(
                                    UserSsoIdentity.user_id == User.id,
                                    UserSsoIdentity.tenant_id == tenant_id,
                                    UserSsoIdentity.provider == mode,
                                )
                                .correlate(User)
                                .exists()
                            )
                        )
                    )
                ).scalars().all()

                for u in users_without_pw:
                    plain = secrets.token_urlsafe(12)
                    u.password_hash = hash_password(plain)
                    u.temp_password_expires_at = temp_expires
                    temp_passwords_out.append({
                        "user_id": u.id,
                        "identifier": u.identifier,
                        "email": u.email,
                        "password": plain,
                        "expires_at": temp_expires.isoformat(),
                    })

        else:
            # Ritorno a "Normale"
            # Genera password temporanee per chi non ha password
            ttl_days = int(os.getenv("AION_SSO_TEMP_PASSWORD_TTL_DAYS", "7"))
            temp_expires = now + timedelta(days=ttl_days)

            users_without_pw = (
                await session.execute(
                    select(User).where(
                        User.tenant_id == tenant_id,
                        User.password_hash.is_(None),
                        User.sso_migration_exempt == False,  # noqa: E712
                    )
                )
            ).scalars().all()

            for u in users_without_pw:
                plain = secrets.token_urlsafe(12)
                u.password_hash = hash_password(plain)
                u.temp_password_expires_at = temp_expires
                u.must_change_password = True
                temp_passwords_out.append({
                    "user_id": u.id,
                    "identifier": u.identifier,
                    "email": u.email,
                    "password": plain,
                    "expires_at": temp_expires.isoformat(),
                })

            if current_row:
                current_row.login_mode = "password"
                current_row.sso_origin = None
                current_row.migration_started_at = None
                current_row.migration_completed_at = None
                current_row.updated_by_user_id = actor_user_id
                current_row.updated_at = now
            else:
                session.add(AuthSettings(
                    tenant_id=tenant_id,
                    login_mode="password",
                    sso_origin=None,
                    updated_by_user_id=actor_user_id,
                    updated_at=now,
                ))

        await session.commit()

    # Step 4: enable/disable provider (fuori dalla transazione principale per semplicità)
    if mode != "password":
        try:
            await enable_provider(tenant_id, mode, True)
        except Exception as e:
            logger.warning("enable_provider failed after set_login_mode: %s", e)
    else:
        # Disabilita tutti i provider
        from src.auth.sso.config_service import admin_list_providers, enable_provider as _ep
        for p in await admin_list_providers(tenant_id):
            if p.get("enabled"):
                try:
                    await _ep(tenant_id, p["provider"], False)
                except Exception:
                    pass

    _invalidate_cache(tenant_id)

    settings = await get_login_settings(tenant_id)
    result = dict(settings)
    if temp_passwords_out:
        result["temp_passwords"] = temp_passwords_out
    return result


async def generate_temp_passwords(
    tenant_id: str,
    user_ids: List[str],
    active_provider: str,
) -> List[Dict]:
    """Genera (o rigenera) password temporanee per gli utenti indicati.

    Usato da POST /admin/auth/temp-passwords.
    """
    from src.data.user_password import hash_password

    ttl_days = int(os.getenv("AION_SSO_TEMP_PASSWORD_TTL_DAYS", "7"))
    now = datetime.now(timezone.utc)
    temp_expires = now + timedelta(days=ttl_days)
    results = []

    async with get_async_session_maker()() as session:
        for uid in user_ids:
            user = await session.get(User, uid)
            if not user or user.tenant_id != tenant_id:
                continue

            # Non generare per chi è già collegato
            already_linked = (
                await session.execute(
                    select(UserSsoIdentity).where(
                        UserSsoIdentity.user_id == uid,
                        UserSsoIdentity.tenant_id == tenant_id,
                        UserSsoIdentity.provider == active_provider,
                    )
                )
            ).scalars().first()
            if already_linked:
                raise ValueError(f"user_already_linked:{uid}")

            plain = secrets.token_urlsafe(12)
            user.password_hash = hash_password(plain)
            user.temp_password_expires_at = temp_expires

            results.append({
                "user_id": uid,
                "identifier": user.identifier,
                "email": user.email,
                "password": plain,
                "expires_at": temp_expires.isoformat(),
            })

        await session.commit()

    _invalidate_cache(tenant_id)
    return results
