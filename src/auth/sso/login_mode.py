"""Servizio login_mode: fonte di verità per la modalità di accesso SSO.

Implementa §2 del piano di migrazione.
"""

import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select, text

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


def _as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite restituisce datetime naive: li normalizza a UTC per i confronti."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def confirmed_identity_exists(tenant_id: str, provider: str, since: Optional[datetime]):
    """Clausola EXISTS (correlata a ``User``): l'utente ha un'identita' per
    ``provider`` confermata nella migrazione corrente.

    Ogni passaggio a SSO apre una nuova migrazione (``migration_started_at``):
    le identita' rimaste da una migrazione precedente (es. SSO -> password ->
    SSO) contano solo se l'utente le ha riconfermate (link o login SSO, che
    aggiornano ``last_login_at``) dopo l'inizio. Con ``since`` NULL
    (first_setup / nessuna migrazione) basta l'esistenza dell'identita'.
    """
    q = select(UserSsoIdentity.id).where(
        UserSsoIdentity.user_id == User.id,
        UserSsoIdentity.tenant_id == tenant_id,
        UserSsoIdentity.provider == provider,
    )
    if since is not None:
        q = q.where(UserSsoIdentity.last_login_at >= since)
    return q.correlate(User).exists()


def is_identity_confirmed(identity: UserSsoIdentity, since: Optional[datetime]) -> bool:
    """Versione Python di :func:`confirmed_identity_exists` per una riga gia' caricata."""
    if since is None:
        return True
    last = _as_aware(identity.last_login_at)
    return last is not None and last >= _as_aware(since)


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
            "sso_signup_policy": "open",
            "sso_signup_allowlist": [],
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
            "sso_signup_policy": normalize_signup_policy(
                getattr(row, "sso_signup_policy", None)
            ),
            "sso_signup_allowlist": parse_signup_allowlist(
                getattr(row, "sso_signup_allowlist", None)
            ),
        }

    _SETTINGS_CACHE[tenant_id] = (now + CACHE_TTL, result)
    return result


# --- Policy nuovi account SSO ----------------------------------------------
# Decide chi puo' ottenere un account al primo login SSO (auto-provisioning).
# Non tocca chi ha gia' un account: per revocare l'accesso si elimina l'utente.

SIGNUP_POLICIES = ("open", "allowlist", "closed")
SIGNUP_ALLOWLIST_MAX = 2000
# L'ultima etichetta del dominio non contiene punti: senza questo vincolo la
# regex torna indietro in tempo quadratico su input come ``a@a.a.a...`` (ReDoS).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]+$")
_MAX_ALLOWLIST_ENTRY = 254  # lunghezza massima di un indirizzo email (RFC 5321)
_DOMAIN_RE = re.compile(
    r"^@[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)


def normalize_signup_policy(value: Optional[str]) -> str:
    v = (value or "open").strip().lower()
    return v if v in SIGNUP_POLICIES else "open"


def parse_signup_allowlist(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip().lower() for x in data if str(x).strip()]


def normalize_allowlist_entry(entry: str) -> Optional[str]:
    """Email completa (``mario@azienda.it``) o dominio (``@azienda.it``).

    Restituisce la voce in minuscolo, oppure None se non valida.
    """
    v = (entry or "").strip().lower()
    if not v or len(v) > _MAX_ALLOWLIST_ENTRY:
        return None
    if v.startswith("@"):
        return v if _DOMAIN_RE.match(v) else None
    return v if _EMAIL_RE.match(v) else None


def signup_denied_reason(
    email: Optional[str], policy: str, allowlist: List[str]
) -> Optional[str]:
    """Codice d'errore se ``email`` non puo' creare un nuovo account, altrimenti None."""
    policy = normalize_signup_policy(policy)
    if policy == "open":
        return None
    if policy == "closed":
        return "sso_signup_closed"
    e = (email or "").strip().lower()
    if not e or "@" not in e:
        return "sso_signup_not_allowed"
    entries = set(allowlist)
    if e in entries or ("@" + e.rsplit("@", 1)[1]) in entries:
        return None
    return "sso_signup_not_allowed"


async def pending_users_count(tenant_id: str, provider: str) -> int:
    """Conta gli utenti con password (o con un link email per impostarla
    ancora valido) che non hanno ancora un'identità SSO per il provider attivo
    e non sono esonerati. Cache di 15s."""
    from src.auth.password_setup import active_setup_link_exists

    cache_key = f"{tenant_id}:{provider}"
    now = time.time()
    cached = _PENDING_CACHE.get(cache_key)
    if cached and now < cached[0]:
        return cached[1]

    since = (await get_login_settings(tenant_id))["migration_started_at"]
    async with get_async_session_maker()() as session:
        # Utenti con password o link attivo, non esonerati, senza identità
        # confermata per questo provider nella migrazione corrente. Senza il
        # link nel conteggio la migrazione si chiuderebbe (e il form password
        # sparirebbe) prima che l'utente abbia impostato la password.
        stmt = (
            select(func.count())
            .select_from(User)
            .where(
                User.tenant_id == tenant_id,
                or_(User.password_hash.is_not(None), active_setup_link_exists()),
                User.sso_migration_exempt == False,  # noqa: E712
            )
            .where(~confirmed_identity_exists(tenant_id, provider, since))
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

        confirmed = (
            await session.execute(
                select(User.id).where(
                    User.id == user_row_id,
                    confirmed_identity_exists(
                        tenant_id, provider, settings["migration_started_at"]
                    ),
                )
            )
        ).first()

    return confirmed is None


def _wipe_totp(user: User) -> None:
    user.totp_secret_encrypted = None
    user.totp_enabled_at = None
    user.totp_last_used_step = None
    user.totp_failed_count = 0
    user.totp_locked_until = None


def sync_user_email(user: User, sso_email: Optional[str]) -> None:
    """L'email dell'utente segue quella del provider SSO attivo (es. dopo un
    passaggio Microsoft -> Google)."""
    email = (sso_email or "").strip().lower()
    if email and user.email != email:
        user.email = email


def finalize_user(user: User, clear_password: bool) -> bool:
    """Applica a un utente appena migrato: via TOTP e scadenza della password
    temporanea; con ``clear_password`` rimuove la password locale, admin
    compresi (accesso di emergenza: ``python -m src.auth.recover``).
    Ritorna True se ha modificato qualcosa."""
    touched = False
    if user.totp_secret_encrypted or user.totp_enabled_at:
        _wipe_totp(user)
        touched = True
    if user.temp_password_expires_at is not None:
        user.temp_password_expires_at = None
        touched = True
    if clear_password and user.password_hash:
        user.password_hash = None
        user.must_change_password = False
        touched = True
    return touched


async def finalize_linked_users(tenant_id: str, provider: str) -> int:
    """Rimuove password e 2FA (TOTP) di chi ha un'identita' SSO confermata
    nella migrazione corrente (vedi :func:`confirmed_identity_exists`).

    La password e' rimossa solo con ``clear_password_on_link`` (admin compresi);
    il TOTP sempre, perche' in modalita' SSO non ha senso. Le identita' rimaste da
    una migrazione precedente non contano: altrimenti un nuovo passaggio a SSO
    cancellerebbe le password temporanee appena emesse.
    Ritorna il numero di utenti modificati.
    """
    changed = 0
    async with get_async_session_maker()() as session:
        settings_row = await session.get(AuthSettings, tenant_id)
        clear_pw = (
            True if settings_row is None else bool(settings_row.clear_password_on_link)
        )
        since = settings_row.migration_started_at if settings_row else None
        users = (
            (
                await session.execute(
                    select(User).where(
                        User.tenant_id == tenant_id,
                        confirmed_identity_exists(tenant_id, provider, since),
                    )
                )
            )
            .scalars()
            .all()
        )
        for u in users:
            changed += 1 if finalize_user(u, clear_pw) else 0
        if changed:
            await session.commit()
    if changed:
        _invalidate_cache(tenant_id)
    return changed


async def _check_migration_completion(tenant_id: str, provider: str) -> None:
    """Se pending_users_count arriva a 0, scrive migration_completed_at e
    ripulisce password/TOTP degli utenti gia' migrati."""
    # Il conteggio e' in cache 15s: senza invalidazione il collegamento appena
    # avvenuto non verrebbe visto e la migrazione non risulterebbe mai completata.
    _invalidate_cache(tenant_id)
    # Con admin_validate siamo ancora in modalita' password: niente pulizia,
    # altrimenti un admin unico utente perderebbe la password prima del passaggio.
    if (await get_login_settings(tenant_id))["login_mode"] != provider:
        return
    count = await pending_users_count(tenant_id, provider)
    if count == 0:
        await finalize_linked_users(tenant_id, provider)
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


async def reopen_migration(tenant_id: str) -> None:
    """Riapre la migrazione quando un utente torna a doversi collegare (es. dopo
    lo scollegamento dell'identita' SSO e l'invio del link per la password).

    Senza riapertura il form password resta nascosto (``first_setup``) e un
    login SSO diretto finirebbe nell'auto-provisioning invece che in
    ``sso_not_linked``. Le identita' gia' confermate restano valide:
    ``migration_started_at`` non cambia (``None`` per chi veniva dal first_setup,
    che fa contare ogni identita' esistente).
    """
    async with get_async_session_maker()() as session:
        row = await session.get(AuthSettings, tenant_id)
        if not row or (row.login_mode or "password") == "password":
            return
        if row.sso_origin == "migration" and not row.migration_completed_at:
            return
        row.sso_origin = "migration"
        row.migration_completed_at = None
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
    _invalidate_cache(tenant_id)
    logger.info("SSO migration reopened for tenant %s", tenant_id)


async def set_login_mode(
    tenant_id: str,
    mode: str,
    *,
    actor_user_id: str,
    provider_validated_at: Optional[datetime] = None,
    revalidation_window_minutes: int = 30,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Cambia la modalità di login. Vedi §3.2.

    Restituisce il dizionario con le impostazioni aggiornate. Se il cambio
    lascia utenti senza modo di accedere, ricevono via email un link per
    impostare la password: l'esito è in 'setup_links' (mai password o token).
    ``ValueError("smtp_not_configured")`` se servono link ma manca lo SMTP.
    """
    from src.auth.sso.config_service import enable_provider, get_provider

    if mode not in ("password", "microsoft", "google"):
        raise ValueError("invalid_mode")

    async with get_async_session_maker()() as session:
        now = datetime.now(timezone.utc)

        # Leggi impostazioni correnti
        current_row = await session.get(AuthSettings, tenant_id)
        current_mode = current_row.login_mode if current_row else "password"

        link_user_ids: List[str] = []

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
                (
                    await session.execute(
                        select(UserSsoIdentity).where(
                            UserSsoIdentity.tenant_id == tenant_id,
                            UserSsoIdentity.user_id == actor_user_id,
                            UserSsoIdentity.provider == mode,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if not actor_identity:
                raise ValueError("sso_admin_not_linked")

            # Calcola origin
            # first_setup solo se il setup non e' concluso E non esistono altri
            # utenti oltre all'admin che sta attivando SSO; altrimenti e' una
            # migrazione (es. passaggio password -> SSO dalle impostazioni).
            first_setup_complete = os.getenv("AION_FIRST_SETUP_COMPLETE") == "1"
            other_users = (
                await session.execute(
                    select(func.count())
                    .select_from(User)
                    .where(User.tenant_id == tenant_id, User.id != actor_user_id)
                )
            ).scalar_one()
            if not first_setup_complete and other_users == 0:
                sso_origin = "first_setup"
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
                # Nuova migrazione: le identita' gia' esistenti vanno
                # riconfermate (vedi confirmed_identity_exists). L'admin che
                # attiva l'SSO ha appena validato il provider: conta come migrato.
                actor_identity.last_login_at = now
                actor = await session.get(User, actor_user_id)
                if actor:
                    sync_user_email(actor, actor_identity.email)
                current_row.login_mode = mode
                current_row.sso_origin = sso_origin
                current_row.migration_started_at = migration_started
                current_row.migration_completed_at = None
                current_row.updated_by_user_id = actor_user_id
                current_row.updated_at = now
            else:
                actor_identity.last_login_at = now
                actor = await session.get(User, actor_user_id)
                if actor:
                    sync_user_email(actor, actor_identity.email)
                session.add(
                    AuthSettings(
                        tenant_id=tenant_id,
                        login_mode=mode,
                        sso_origin=sso_origin,
                        migration_started_at=migration_started,
                        migration_completed_at=None,
                        clear_password_on_link=True,
                        updated_by_user_id=actor_user_id,
                        updated_at=now,
                    )
                )

            # Step 4-bis: cambio da SSO a SSO — link email per impostare la
            # password a chi non ce l'ha e non ha identità per il nuovo provider
            if current_mode in ("microsoft", "google") and current_mode != mode:
                users_without_pw = (
                    (
                        await session.execute(
                            select(User)
                            .where(
                                User.tenant_id == tenant_id,
                                User.password_hash.is_(None),
                                User.sso_migration_exempt == False,  # noqa: E712
                                User.id != actor_user_id,
                            )
                            .where(
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
                    )
                    .scalars()
                    .all()
                )

                link_user_ids = [u.id for u in users_without_pw]

        else:
            # Ritorno a "Normale": link email a chi non ha password
            users_without_pw = (
                (
                    await session.execute(
                        select(User).where(
                            User.tenant_id == tenant_id,
                            User.password_hash.is_(None),
                            User.sso_migration_exempt == False,  # noqa: E712
                        )
                    )
                )
                .scalars()
                .all()
            )

            link_user_ids = [u.id for u in users_without_pw]

            if current_row:
                current_row.login_mode = "password"
                current_row.sso_origin = None
                current_row.migration_started_at = None
                current_row.migration_completed_at = None
                current_row.updated_by_user_id = actor_user_id
                current_row.updated_at = now
            else:
                session.add(
                    AuthSettings(
                        tenant_id=tenant_id,
                        login_mode="password",
                        sso_origin=None,
                        updated_by_user_id=actor_user_id,
                        updated_at=now,
                    )
                )

        # Senza SMTP questi utenti resterebbero chiusi fuori: niente cambio.
        if link_user_ids:
            from src.notifications.smtp_settings import smtp_configured

            if not await smtp_configured(tenant_id):
                raise ValueError("smtp_not_configured")

        await session.commit()

    # Link inviati prima del controllo di completamento: chi ha un link
    # attivo conta come "in attesa" (pending_users_count).
    setup_links: Optional[Dict[str, Any]] = None
    if link_user_ids:
        setup_links = await _send_links(
            tenant_id, link_user_ids, actor_user_id=actor_user_id, base_url=base_url
        )

    # Step 4: enable/disable provider (fuori dalla transazione principale per semplicità)
    if mode != "password":
        try:
            await enable_provider(tenant_id, mode, True)
        except Exception as e:
            logger.warning("enable_provider failed after set_login_mode: %s", e)
        # Chi e' gia' migrato (l'admin che attiva) perde TOTP e password locale.
        # Gli altri conservano il 2FA, richiesto al login con password finche'
        # non collegano l'account SSO (finalize_user).
        await finalize_linked_users(tenant_id, mode)
        await _check_migration_completion(tenant_id, mode)
    else:
        # Disabilita tutti i provider
        from src.auth.sso.config_service import (
            admin_list_providers,
            enable_provider as _ep,
        )

        for p in await admin_list_providers(tenant_id):
            if p.get("enabled"):
                try:
                    await _ep(tenant_id, p["provider"], False)
                except Exception:
                    pass

    _invalidate_cache(tenant_id)

    settings = await get_login_settings(tenant_id)
    result = dict(settings)
    if setup_links is not None:
        result["setup_links"] = setup_links
    return result


async def _send_links(
    tenant_id: str,
    user_ids: List[str],
    *,
    actor_user_id: Optional[str],
    base_url: Optional[str],
) -> Dict[str, Any]:
    from src.api.public_urls import chat_base_url
    from src.auth.password_setup import SetupLinkError, issue_setup_links

    try:
        return await issue_setup_links(
            tenant_id,
            user_ids,
            "migration",
            actor_user_id=actor_user_id,
            base_url=base_url or chat_base_url(),
        )
    except SetupLinkError as e:
        # SMTP disattivato tra il controllo e l'invio: nessun link creato.
        failed = [{"user_id": uid, "reason": e.code} for uid in user_ids]
        return {"sent": [], "failed": failed, "missing_email": []}


async def send_migration_links(
    tenant_id: str,
    user_ids: List[str],
    active_provider: str,
    *,
    actor_user_id: Optional[str],
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Invia (o reinvia) via email il link per impostare la password agli
    utenti indicati, che poi collegheranno l'account SSO.

    Usato da POST /admin/auth/setup-links e dallo scollegamento di un'identita'.
    ``ValueError("user_already_linked:<id>")`` per chi e' gia' collegato,
    ``ValueError("smtp_not_configured")`` senza SMTP.
    """
    from src.notifications.smtp_settings import smtp_configured

    async with get_async_session_maker()() as session:
        for uid in user_ids:
            already_linked = (
                (
                    await session.execute(
                        select(UserSsoIdentity).where(
                            UserSsoIdentity.user_id == uid,
                            UserSsoIdentity.tenant_id == tenant_id,
                            UserSsoIdentity.provider == active_provider,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if already_linked:
                raise ValueError(f"user_already_linked:{uid}")
    if not await smtp_configured(tenant_id):
        raise ValueError("smtp_not_configured")

    result = await _send_links(
        tenant_id, user_ids, actor_user_id=actor_user_id, base_url=base_url
    )
    # Chi riceve il link deve (ri)collegarsi: serve il form password e la
    # migrazione deve risultare in corso.
    if result["sent"] or result["failed"]:
        await reopen_migration(tenant_id)
    return result
