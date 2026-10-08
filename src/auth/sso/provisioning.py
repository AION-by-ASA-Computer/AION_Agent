"""SSO User Provisioning and resolution.

Fix 0.7: allowed_domains, email_verified, subject corretto per MS.
Fix 0.8: nessun auto-link per email/identifier da resolve_user.
         link_identity_to_user: collegamento esplicito autenticato.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.chat_auth import _user_to_auth_dict
from src.data.engine import get_async_session_maker
from src.data.ids import new_uuid7_str
from src.data.models import User, UserSsoIdentity
from src.runtime.credential_store import encrypt_value

logger = logging.getLogger("aion.sso.provisioning")


def _extract_subject_and_email(
    claims: Dict[str, Any],
    provider: str,
) -> tuple[str, str]:
    """Restituisce (subject, email) in modo sicuro per ogni provider.

    Fix 0.7: per Microsoft usa tid:oid come subject (non l'email).
    Fix 0.7: per Google verifica email_verified.
    """
    if provider == "microsoft":
        tid = claims.get("tid")
        oid = claims.get("oid")
        if not tid or not oid:
            raise ValueError("missing_subject_claims")
        subject = f"{tid}:{oid}"
        # Email è solo informativa per MS, non usata per il collegamento
        email = (claims.get("preferred_username") or claims.get("email") or "").strip().lower()
    elif provider == "google":
        subject = claims.get("sub")
        if not subject:
            raise ValueError("missing_subject_claims")
        # email_verified già verificata da verify_id_token (fix 0.7)
        email = (claims.get("email") or "").strip().lower()
    else:
        raise ValueError("unsupported_provider")

    return subject, email


async def resolve_user(
    claims: Dict[str, Any],
    token_data: Dict[str, Any],
    provider_config: Dict[str, Any],
    tenant_id: str = "default",
    migration_active: bool = False,
) -> Dict[str, Any]:
    """Risolve un utente dal login SSO diretto (purpose=login).

    Fix 0.8: NON esegue più auto-link per email/identifier.
    Solo identità esistente → login oppure auto-provisioning (se non in migrazione).
    """
    provider = provider_config["provider"]
    subject, email = _extract_subject_and_email(claims, provider)

    display_name = claims.get("name") or claims.get("given_name") or email
    now = datetime.now(timezone.utc)
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in")
    token_expires_at = now + timedelta(seconds=expires_in) if expires_in else None
    access_token_encrypted = encrypt_value(access_token) if access_token else None

    async with get_async_session_maker()() as session:
        # 1. Cerca identità esistente per (tenant, provider, subject)
        identity = (
            await session.execute(
                select(UserSsoIdentity).where(
                    UserSsoIdentity.tenant_id == tenant_id,
                    UserSsoIdentity.provider == provider,
                    UserSsoIdentity.subject == subject,
                )
            )
        ).scalars().first()

        if identity:
            # Login normale con identità già collegata
            user = (
                await session.execute(select(User).where(User.id == identity.user_id))
            ).scalars().first()
            if user:
                user.last_active_at = now
                identity.access_token_encrypted = access_token_encrypted
                identity.token_expires_at = token_expires_at
                # last_login_at >= migration_started_at conferma l'identita'
                # nella migrazione corrente (vedi confirmed_identity_exists).
                identity.last_login_at = now
                identity.updated_at = now
                if email:
                    identity.email = email
                    identity.display_name = display_name
                from src.auth.sso.login_mode import sync_user_email

                sync_user_email(user, email)
                if migration_active:
                    # Login SSO con identita' di una migrazione precedente:
                    # vale come collegamento, l'utente e' migrato.
                    from src.auth.sso.login_mode import finalize_user, get_login_settings

                    settings = await get_login_settings(tenant_id)
                    finalize_user(user, settings.get("clear_password_on_link", True))
                await session.commit()
                await session.refresh(user)
                if migration_active:
                    from src.auth.sso.login_mode import _check_migration_completion

                    await _check_migration_completion(tenant_id, provider)
                return _user_to_auth_dict(user)

        # Fix 0.8: nessun auto-link per email/identifier.
        # 2. Migrazione attiva → errore, l'utente deve usare la password prima
        if migration_active:
            raise ValueError("sso_not_linked")

        # 3. Auto-provisioning (solo se migrazione non attiva e auto_provision=True)
        if not provider_config.get("auto_provision", True):
            raise ValueError("sso_not_linked")

        if not email:
            raise ValueError("email_required_for_provisioning")

        # Verifica allowed_domains (fix 0.7) — già verificata in id_token,
        # ma ri-verifichiamo qui per sicurezza.
        allowed_domains = provider_config.get("allowed_domains", [])
        if allowed_domains:
            domain = email.split("@")[-1] if "@" in email else ""
            if domain not in allowed_domains:
                raise ValueError("sso_domain_not_allowed")

        user_id = new_uuid7_str()
        roles_json = json.dumps(provider_config.get("default_roles") or ["user"])
        meta_json = json.dumps({"sso_provider": provider})

        user = User(
            id=user_id,
            tenant_id=tenant_id,
            identifier=email,
            display_name=display_name,
            email=email,
            password_hash=None,
            roles_json=roles_json,
            metadata_json=meta_json,
            created_at=now,
            last_active_at=now,
        )
        session.add(user)

        new_identity = UserSsoIdentity(
            id=new_uuid7_str(),
            tenant_id=tenant_id,
            user_id=user_id,
            provider=provider,
            subject=subject,
            email=email,
            display_name=display_name,
            access_token_encrypted=access_token_encrypted,
            token_expires_at=token_expires_at,
            last_login_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(new_identity)

        try:
            await session.commit()
        except IntegrityError:
            # Race condition: un altro processo ha creato lo stesso utente.
            await session.rollback()
            raise ValueError("sso_provisioning_conflict")

        await session.refresh(user)
        logger.info("Auto-provisioned new SSO user %s via %s", user_id, provider)

    return _user_to_auth_dict(user)


async def link_identity_to_user(
    tenant_id: str,
    user_id: str,
    claims: Dict[str, Any],
    token_data: Dict[str, Any],
    provider_config: Dict[str, Any],
    finalize_migration: bool = False,
) -> None:
    """Collega un'identità SSO a un utente locale già autenticato.

    Usato da:
    - purpose=link (utente normale dopo login con password)
    - purpose=admin_validate (admin che conferma il provider)

    Fix 0.8: SOLO questo flusso può collegare identità. Nessun auto-link.

    ``finalize_migration=True`` (solo purpose=link): a collegamento avvenuto
    azzera la scadenza della password temporanea e, se
    ``auth_settings.clear_password_on_link`` e' attivo, rimuove la password
    locale (l'utente entra solo via SSO), admin compresi: l'accesso di emergenza
    passa da ``python -m src.auth.recover``. Con ``admin_validate`` resta False:
    l'admin non e' ancora passato a SSO.
    """
    provider = provider_config["provider"]
    subject, email = _extract_subject_and_email(claims, provider)

    display_name = claims.get("name") or claims.get("given_name") or email
    now = datetime.now(timezone.utc)
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in")
    token_expires_at = now + timedelta(seconds=expires_in) if expires_in else None
    access_token_encrypted = encrypt_value(access_token) if access_token else None

    async with get_async_session_maker()() as session:
        # Verifica che (tenant, provider, subject) non sia già collegato
        # a un ALTRO utente
        existing_identity = (
            await session.execute(
                select(UserSsoIdentity).where(
                    UserSsoIdentity.tenant_id == tenant_id,
                    UserSsoIdentity.provider == provider,
                    UserSsoIdentity.subject == subject,
                )
            )
        ).scalars().first()

        from src.auth.sso.login_mode import (
            finalize_user,
            get_login_settings,
            is_identity_confirmed,
            sync_user_email,
        )

        settings = await get_login_settings(tenant_id)

        if existing_identity and existing_identity.user_id != user_id:
            raise ValueError("sso_already_linked")

        # Verifica che l'utente esista
        user = await session.get(User, user_id)
        if not user:
            raise ValueError("user_not_found")

        # last_login_at = now conferma l'identita' nella migrazione corrente
        # (vedi confirmed_identity_exists), anche quando la riga esiste gia'.
        identity = existing_identity
        if identity is None:
            # Verifica che l'utente non abbia già un'identità per questo provider
            # con un subject diverso
            identity = (
                await session.execute(
                    select(UserSsoIdentity).where(
                        UserSsoIdentity.tenant_id == tenant_id,
                        UserSsoIdentity.user_id == user_id,
                        UserSsoIdentity.provider == provider,
                    )
                )
            ).scalars().first()
            if identity is not None:
                if is_identity_confirmed(identity, settings.get("migration_started_at")):
                    # Subject diverso → solo l'admin può scollegare
                    raise ValueError("sso_user_already_linked")
                # Identita' di una migrazione precedente: in una nuova
                # migrazione l'utente puo' collegare un account diverso.
                identity.subject = subject

        if identity is None:
            session.add(UserSsoIdentity(
                id=new_uuid7_str(),
                tenant_id=tenant_id,
                user_id=user_id,
                provider=provider,
                subject=subject,
                email=email,
                display_name=display_name,
                access_token_encrypted=access_token_encrypted,
                token_expires_at=token_expires_at,
                last_login_at=now,
                created_at=now,
                updated_at=now,
            ))
        else:
            identity.access_token_encrypted = access_token_encrypted
            identity.token_expires_at = token_expires_at
            identity.last_login_at = now
            identity.updated_at = now
            if email:
                identity.email = email
                identity.display_name = display_name

        # Se l'utente non ha email, popolala con quella SSO; a migrazione
        # confermata vale quella del nuovo provider. Con admin_validate (non
        # ancora passato) l'email resta invariata.
        if not user.email and email:
            user.email = email

        if finalize_migration:
            sync_user_email(user, email)
            # Il 2FA TOTP vale solo per il login con password.
            finalize_user(user, bool(settings.get("clear_password_on_link")))

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise ValueError("sso_already_linked")

        logger.info(
            "Linked SSO identity %s (%s) to user %s",
            subject,
            provider,
            user_id,
        )

    # Verifica se l'operazione ha completato la migrazione
    from src.auth.sso.login_mode import _check_migration_completion
    await _check_migration_completion(tenant_id, provider)
