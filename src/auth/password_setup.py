"""Link monouso via email per impostare la password.

L'admin non vede mai ne' la password ne' il link: il token in chiaro esiste
solo nell'email inviata all'utente; nel DB resta lo SHA-256
(``password_setup_tokens``). Scopi:

- ``invite``: nuovo account creato dall'admin;
- ``reset``: reimpostazione (da admin o "Password dimenticata?");
- ``migration``: utenti senza password durante un cambio di modalita' SSO.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update

from src.data.engine import get_async_session_maker
from src.data.ids import new_uuid7_str
from src.data.models import PasswordSetupToken, User, UserSsoIdentity
from src.notifications import email_templates
from src.notifications.mailer import EmailSendError, send_email
from src.notifications.smtp_settings import get_smtp_config

logger = logging.getLogger("aion.auth.password_setup")

PURPOSES = ("invite", "reset", "migration")


class SetupLinkError(Exception):
    """Errore applicativo con ``code`` stabile per le API."""

    def __init__(self, code: str, violations: Optional[List[str]] = None) -> None:
        self.code = code
        self.violations = violations or []
        super().__init__(code)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _ttl(purpose: str) -> timedelta:
    if purpose == "reset":
        return timedelta(
            minutes=int(os.getenv("AION_PASSWORD_RESET_TTL_MINUTES", "60"))
        )
    if purpose == "migration":
        return timedelta(days=int(os.getenv("AION_SSO_TEMP_PASSWORD_TTL_DAYS", "7")))
    return timedelta(hours=int(os.getenv("AION_PASSWORD_INVITE_TTL_HOURS", "72")))


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def platform_name() -> str:
    return (os.getenv("AION_EMAIL_PLATFORM_NAME") or "AION").strip() or "AION"


def active_setup_link_exists():
    """Clausola EXISTS (correlata a ``User``): link non usato e non scaduto."""
    return (
        select(PasswordSetupToken.id)
        .where(
            PasswordSetupToken.user_id == User.id,
            PasswordSetupToken.consumed_at.is_(None),
            PasswordSetupToken.expires_at > _now(),
        )
        .correlate(User)
        .exists()
    )


async def active_links_by_user(tenant_id: str) -> Dict[str, Dict[str, Any]]:
    """Ultimo link attivo per utente: ``{user_id: {purpose, expires_at, send_error}}``."""
    out: Dict[str, Dict[str, Any]] = {}
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(PasswordSetupToken)
                    .where(
                        PasswordSetupToken.tenant_id == tenant_id,
                        PasswordSetupToken.consumed_at.is_(None),
                        PasswordSetupToken.expires_at > _now(),
                    )
                    .order_by(PasswordSetupToken.created_at)
                )
            )
            .scalars()
            .all()
        )
    for t in rows:
        out[t.user_id] = {
            "purpose": t.purpose,
            "expires_at": _as_aware(t.expires_at).isoformat(),
            "send_error": t.send_error,
        }
    return out


def _format_expiry(dt: datetime, lang: str) -> str:
    dt = _as_aware(dt).astimezone(timezone.utc)
    if lang == "en":
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    return dt.strftime("%d/%m/%Y %H:%M UTC")


def build_link(base_url: str, raw_token: str) -> str:
    # Token nel fragment: non arriva nei log del server ne' nel Referer.
    return f"{base_url.rstrip('/')}/set-password#token={raw_token}"


async def issue_setup_links(
    tenant_id: str,
    user_ids: List[str],
    purpose: str,
    *,
    actor_user_id: Optional[str],
    base_url: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Crea un link per ogni utente e lo invia via email.

    Invalida i link precedenti dello stesso utente. Ritorna
    ``{"sent": [...], "failed": [...], "missing_email": [...]}`` con
    ``user_id``/``identifier``/``email`` (mai il token).
    Solleva ``SetupLinkError("smtp_not_configured")`` prima di toccare il DB.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"invalid purpose: {purpose}")
    cfg = await get_smtp_config(tenant_id)
    if cfg is None:
        raise SetupLinkError("smtp_not_configured")

    now = _now()
    expires = now + _ttl(purpose)
    result: Dict[str, List[Dict[str, Any]]] = {
        "sent": [],
        "failed": [],
        "missing_email": [],
    }
    to_send: List[Dict[str, Any]] = []

    async with get_async_session_maker()() as session:
        for uid in user_ids:
            user = await session.get(User, uid)
            if not user or user.tenant_id != tenant_id:
                continue
            info = {
                "user_id": user.id,
                "identifier": user.identifier,
                "email": user.email,
            }
            if not (user.email or "").strip():
                result["missing_email"].append(info)
                continue
            await session.execute(
                update(PasswordSetupToken)
                .where(
                    PasswordSetupToken.user_id == user.id,
                    PasswordSetupToken.consumed_at.is_(None),
                )
                .values(consumed_at=now)
            )
            raw = secrets.token_urlsafe(32)
            row = PasswordSetupToken(
                id=new_uuid7_str(),
                tenant_id=tenant_id,
                user_id=user.id,
                token_hash=hash_token(raw),
                purpose=purpose,
                created_by_user_id=actor_user_id,
                created_at=now,
                expires_at=expires,
            )
            session.add(row)
            to_send.append(
                {
                    "row_id": row.id,
                    "raw": raw,
                    "info": info,
                    "name": user.display_name or user.identifier,
                }
            )
        await session.commit()

    lang = cfg.email_language
    for item in to_send:
        info = item["info"]
        subject, text, html = email_templates.render(
            purpose,
            lang,
            {
                "name": item["name"],
                "identifier": info["identifier"],
                "link": build_link(base_url, item["raw"]),
                "expires": _format_expiry(expires, lang),
                "platform": platform_name(),
            },
        )
        error: Optional[str] = None
        try:
            await send_email(
                tenant_id,
                to=info["email"],
                subject=subject,
                text=text,
                html=html,
                cfg=cfg,
            )
        except EmailSendError as e:
            error = e.code
            logger.warning(
                "Invio link %s a user %s fallito: %s", purpose, info["user_id"], e
            )
        async with get_async_session_maker()() as session:
            row = await session.get(PasswordSetupToken, item["row_id"])
            if row is not None:
                row.sent_at = None if error else _now()
                row.send_error = error
                await session.commit()
        entry = {**info, "expires_at": expires.isoformat()}
        if error:
            result["failed"].append({**entry, "reason": error})
        else:
            result["sent"].append(entry)

    if to_send:
        from src.auth.sso.login_mode import _invalidate_cache

        _invalidate_cache(tenant_id)
    return result


async def _load_valid_token(session, raw: str) -> PasswordSetupToken:
    row = (
        (
            await session.execute(
                select(PasswordSetupToken).where(
                    PasswordSetupToken.token_hash == hash_token(raw or "")
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None or row.consumed_at is not None:
        raise SetupLinkError("token_invalid")
    if _as_aware(row.expires_at) <= _now():
        raise SetupLinkError("token_expired")
    return row


async def _user_signs_in_with_sso(session, user: User) -> bool:
    """True se l'utente e' gia' migrato al provider SSO attivo: impostare una
    password locale riaprirebbe l'accesso classico."""
    from src.auth.sso.login_mode import get_login_settings, is_identity_confirmed

    settings = await get_login_settings(user.tenant_id)
    provider = settings.get("sso_provider")
    if not provider or bool(user.sso_migration_exempt):
        return False
    idents = (
        (
            await session.execute(
                select(UserSsoIdentity).where(
                    UserSsoIdentity.user_id == user.id,
                    UserSsoIdentity.provider == provider,
                )
            )
        )
        .scalars()
        .all()
    )
    since = settings.get("migration_started_at")
    return any(is_identity_confirmed(i, since) for i in idents)


async def inspect_token(raw: str) -> Dict[str, Any]:
    """Dati da mostrare nella pagina di impostazione (non consuma il token)."""
    async with get_async_session_maker()() as session:
        row = await _load_valid_token(session, raw)
        user = await session.get(User, row.user_id)
        if user is None:
            raise SetupLinkError("token_invalid")
        return {
            "valid": True,
            "purpose": row.purpose,
            "identifier": user.identifier,
            "display_name": user.display_name or user.identifier,
            "expires_at": _as_aware(row.expires_at).isoformat(),
        }


async def consume_token(raw: str, new_password: str) -> Dict[str, Any]:
    """Imposta la password scelta dall'utente e brucia il token."""
    from src.auth.sso.login_mode import _invalidate_cache
    from src.data.user_password import (
        get_roles,
        hash_password,
        password_policy_violations,
    )

    now = _now()
    async with get_async_session_maker()() as session:
        row = await _load_valid_token(session, raw)
        user = await session.get(User, row.user_id)
        if user is None:
            raise SetupLinkError("token_invalid")
        # Policy prima del consumo: con una password debole l'utente riprova.
        violations = password_policy_violations(new_password, user.identifier)
        if violations:
            raise SetupLinkError("password_policy", violations)
        if await _user_signs_in_with_sso(session, user):
            raise SetupLinkError("sso_user")

        # Consumo atomico: due richieste concorrenti non possono riuscire entrambe.
        res = await session.execute(
            update(PasswordSetupToken)
            .where(
                PasswordSetupToken.id == row.id,
                PasswordSetupToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        if res.rowcount != 1:
            await session.rollback()
            raise SetupLinkError("token_invalid")
        # Gli altri link eventualmente ancora aperti non servono piu'.
        await session.execute(
            update(PasswordSetupToken)
            .where(
                PasswordSetupToken.user_id == user.id,
                PasswordSetupToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        user.temp_password_expires_at = None
        tenant_id = user.tenant_id
        result = {
            "status": "ok",
            "identifier": user.identifier,
            "is_admin": "admin" in get_roles(user),
        }
        await session.commit()

    _invalidate_cache(tenant_id)
    logger.info(
        "Password impostata via link (%s) per user %s", row.purpose, row.user_id
    )
    return result


async def find_user_for_reset(
    tenant_id: str, identifier_or_email: str
) -> Optional[User]:
    """Utente per "Password dimenticata?": per identifier, oppure per email se
    corrisponde a un solo account."""
    key = (identifier_or_email or "").strip()
    if not key:
        return None
    async with get_async_session_maker()() as session:
        user = (
            (
                await session.execute(
                    select(User).where(
                        User.tenant_id == tenant_id, User.identifier == key
                    )
                )
            )
            .scalars()
            .first()
        )
        if user is None and "@" in key:
            matches = (
                (await session.execute(select(User).where(User.tenant_id == tenant_id)))
                .scalars()
                .all()
            )
            by_email = [
                u for u in matches if (u.email or "").strip().lower() == key.lower()
            ]
            user = by_email[0] if len(by_email) == 1 else None
        if user is not None and await _user_signs_in_with_sso(session, user):
            return None
        return user


async def user_link_block_reason(user: User) -> Optional[str]:
    """Motivo per cui non si puo' inviare un link all'utente, o None."""
    if not (user.email or "").strip():
        return "user_email_missing"
    async with get_async_session_maker()() as session:
        if await _user_signs_in_with_sso(session, user):
            return "password_set_for_sso_user"
    return None


def normalize_email(value: Optional[str]) -> Optional[str]:
    """Email in minuscolo se valida, altrimenti None."""
    from src.auth.sso.login_mode import normalize_allowlist_entry

    v = (value or "").strip().lower()
    if not v or v.startswith("@"):
        return None
    return normalize_allowlist_entry(v)
