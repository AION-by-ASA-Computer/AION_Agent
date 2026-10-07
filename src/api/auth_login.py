"""Login password per chat-ui (token opaco HMAC, senza dipendenze JWT esterne).

Espone anche:

- ``require_chat_auth``: dipendenza FastAPI da applicare agli endpoint user-facing
  della chat. Se ``AION_CHAT_PASSWORD_AUTH=1`` richiede un Bearer token valido
  emesso da ``POST /auth/login`` (oppure una API key con scope ``chat`` per
  l'accesso programmatico). Se la password auth e' disabilitata e' un no-op
  e accetta anche le richieste senza header.
- ``GET /auth/status``: endpoint pubblico che il frontend usa per sapere se
  deve forzare il login.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from src.chat_auth import (
    authenticate_user_password,
    chat_auth_secret,
    password_auth_enabled,
)
from src.identity import sanitize_user_id


# API key persistite iniziano con "aion_" (vedi src/api/auth/api_key.py).
# Il token emesso da /auth/login e' base64-urlsafe puro: non collide.
def _looks_like_api_key(token: str) -> bool:
    return token.startswith("aion_")


logger = logging.getLogger("aion.api.auth_login")

router = APIRouter(prefix="/auth", tags=["auth"])

_TOKEN_TTL_SEC = int(os.getenv("AION_CHAT_AUTH_TOKEN_TTL_SEC", str(7 * 24 * 3600)))


def _secret() -> str:
    # chat_auth_secret() legge AION_CHAT_AUTH_SECRET
    s = chat_auth_secret()
    if not s:
        return "aion-chat-auth-dev-insecure"
    return s


def _encode_roles(roles: Optional[List[str]]) -> str:
    """CSV URL-safe dei ruoli. Vuoto se nessun ruolo. Vieta ':' nei nomi."""
    if not roles:
        return ""
    safe = [r.replace(":", "_").replace(",", "_") for r in roles if r]
    return ",".join(safe)


def _decode_roles(raw: str) -> List[str]:
    if not raw:
        return []
    return [s for s in raw.split(",") if s]


def issue_chat_token(
    *,
    user_row_id: str,
    user_identifier: str,
    roles: Optional[List[str]] = None,
) -> str:
    """Token URL-safe: ``user_row_id:user_identifier:roles_csv:exp:hmac``.

    I ruoli sono inclusi nel payload e firmati HMAC: nessun DB lookup per
    request. TTL = ``AION_CHAT_AUTH_TOKEN_TTL_SEC`` (default 7gg).
    """
    exp = int(time.time()) + max(300, _TOKEN_TTL_SEC)
    roles_csv = _encode_roles(roles)
    payload = f"{user_row_id}:{user_identifier}:{roles_csv}:{exp}"
    sig = hmac.new(
        _secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    raw = f"{payload}:{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def verify_chat_token(token: str) -> Optional[Dict[str, Any]]:
    """Valida il token e ne estrae il payload.

    Supporta sia il formato attuale ``user_row_id:identifier:roles:exp:sig``
    sia il legacy ``user_row_id:identifier:exp:sig`` (in quel caso
    ``roles=[]``), per non invalidare i token gia' emessi.
    """
    if not token or not token.strip():
        return None
    try:
        raw = base64.urlsafe_b64decode(token.strip().encode("ascii"))
        parts = raw.decode("utf-8").rsplit(":", 1)
        if len(parts) != 2:
            return None
        body, sig = parts
        expect = hmac.new(
            _secret().encode("utf-8"), body.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return None
        bits = body.split(":")
        if len(bits) == 4:
            user_row_id, user_identifier, roles_csv, exp_s = bits
            roles = _decode_roles(roles_csv)
        elif len(bits) == 3:
            # Token legacy senza roles
            user_row_id, user_identifier, exp_s = bits
            roles = []
        else:
            return None
        if int(exp_s) < int(time.time()):
            return None
        return {
            "user_row_id": user_row_id,
            "identifier": user_identifier,
            "roles": roles,
        }
    except Exception:
        return None


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    client: str = Field(default="chat")  # "chat" | "admin" (§3.5)


@router.post("/login")
async def login(body: LoginBody):
    # /auth/login resta abilitato se ALMENO una delle due auth e' attiva
    # (chat o admin). Esempio: chat aperta in dev ma admin sempre protetto.
    if not password_auth_enabled() and not admin_password_auth_enabled():
        raise HTTPException(
            503,
            detail=(
                "Password auth disabled (set AION_CHAT_PASSWORD_AUTH=1 or "
                "AION_ADMIN_PASSWORD_AUTH=1 and provision user passwords)."
            ),
        )
    row = await authenticate_user_password(body.username, body.password)
    if not row:
        raise HTTPException(401, detail="Invalid credentials")

    # Controllo password temporanea scaduta (§3.5)
    from src.data.engine import get_async_session_maker as _gsm
    from src.data.models import User as _User
    from datetime import timezone as _tz
    import datetime as _dt

    user_id_raw = str(row["id"])
    async with _gsm()() as _sess:
        _u = await _sess.get(_User, user_id_raw)
        if _u and _u.temp_password_expires_at:
            _now = _dt.datetime.now(_tz.utc)
            _exp = _u.temp_password_expires_at
            if _exp.tzinfo is None:
                _exp = _exp.replace(tzinfo=_tz.utc)
            if _exp < _now:
                raise HTTPException(
                    401,
                    detail={"code": "temp_password_expired"},
                )

    uid = sanitize_user_id(str(row["identifier"]))
    roles = list(row.get("roles") or [])
    must_change = bool(row.get("must_change_password", False))
    tok = issue_chat_token(
        user_row_id=user_id_raw,
        user_identifier=str(row["identifier"]),
        roles=roles,
    )

    # Controlli SSO per client="chat" (§3.5)
    sso_link_required = False
    if body.client == "chat" and password_auth_enabled():
        tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()
        try:
            from src.auth.sso.login_mode import (
                get_login_settings,
                password_login_visible,
                user_needs_link,
            )
            settings = await get_login_settings(tenant)
            login_mode = settings.get("login_mode", "password")

            if login_mode != "password":
                vis = await password_login_visible(tenant)
                if not vis:
                    raise HTTPException(
                        403,
                        detail={"code": "password_login_disabled"},
                    )
                needs_link = await user_needs_link(tenant, user_id_raw)
                if needs_link:
                    sso_link_required = True
                else:
                    # L'utente è già migrato: deve usare solo SSO
                    raise HTTPException(
                        403,
                        detail={"code": "sso_required"},
                    )
        except HTTPException:
            raise
        except Exception as _e:
            logger.warning("SSO login check failed: %s", _e)

    return {
        "access_token": tok,
        "token_type": "bearer",
        "user_id": uid,
        "identifier": row["identifier"],
        "display_name": row.get("display_name") or row["identifier"],
        "roles": roles,
        "must_change_password": must_change,
        "sso_link_required": sso_link_required,
    }


@router.get("/me")
async def me(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    parsed = verify_chat_token(token)
    if not parsed:
        raise HTTPException(401, detail="Invalid or expired token")

    uid = sanitize_user_id(str(parsed["identifier"]))
    user_row_id = parsed["user_row_id"]

    import json as _json
    from src.data.engine import get_async_session_maker
    from src.data.models import User, UserSsoIdentity
    from src.data.user_password import get_roles

    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()

    # Controlla se l'utente deve ancora collegarsi all'SSO (§3.5)
    sso_link_required = False
    sso_linked = False
    sso_provider_name = None
    try:
        from src.auth.sso.login_mode import get_login_settings, user_needs_link
        settings = await get_login_settings(tenant)
        sso_provider_name = settings.get("sso_provider")
        if sso_provider_name:
            sso_link_required = await user_needs_link(tenant, user_row_id)
            sso_linked = not sso_link_required
    except Exception as _e:
        logger.warning("SSO me check failed: %s", _e)

    async with get_async_session_maker()() as session:
        u = await session.get(User, user_row_id)
        if not u:
            return {
                "user_id": uid,
                "identifier": parsed["identifier"],
                "metadata": {},
                "roles": parsed.get("roles", []),
                "must_change_password": False,
                "sso_link_required": sso_link_required,
                "sso_linked": sso_linked,
                "sso_provider": sso_provider_name,
            }

        meta: Dict[str, Any] = {}
        if u.metadata_json:
            try:
                meta = _json.loads(u.metadata_json)
            except Exception:
                pass

        return {
            "user_id": uid,
            "identifier": parsed["identifier"],
            "display_name": u.display_name or u.identifier,
            "email": u.email,
            "metadata": meta,
            "roles": get_roles(u),
            "must_change_password": bool(getattr(u, "must_change_password", False)) and not sso_linked,
            "first_setup_complete": os.getenv("AION_FIRST_SETUP_COMPLETE") == "1",
            "sso_link_required": sso_link_required,
            "sso_linked": sso_linked,
            "sso_provider": sso_provider_name,
        }


class UpdateUserMetadata(BaseModel):
    identifier: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.patch("/me")
async def update_me(
    body: UpdateUserMetadata, authorization: Optional[str] = Header(None)
):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    parsed = verify_chat_token(token)
    if not parsed:
        raise HTTPException(401, detail="Invalid or expired token")

    user_row_id = parsed["user_row_id"]

    import json
    from src.data.engine import get_async_session_maker
    from src.data.models import User

    async with get_async_session_maker()() as session:
        u = await session.get(User, user_row_id)
        if not u:
            raise HTTPException(404, detail="User not found")

        if body.identifier is not None:
            new_identifier = body.identifier.strip()
            if not new_identifier:
                raise HTTPException(
                    400, detail="Username (Nome utente) cannot be empty"
                )
            if new_identifier != u.identifier:
                from sqlalchemy import select

                stmt = select(User).where(
                    User.tenant_id == u.tenant_id, User.identifier == new_identifier
                )
                existing = await session.execute(stmt)
                if existing.scalar_one_or_none():
                    raise HTTPException(
                        400, detail="Username (Nome utente) already taken"
                    )
                u.identifier = new_identifier

        if body.display_name is not None:
            u.display_name = body.display_name.strip() or None

        if body.email is not None:
            u.email = body.email.strip() or None

        meta = {}
        if u.metadata_json:
            try:
                meta = json.loads(u.metadata_json)
            except Exception:
                pass

        if body.metadata is not None:
            meta.update(body.metadata)
            u.metadata_json = json.dumps(meta)

        session.add(u)
        await session.commit()

        return {
            "user_id": sanitize_user_id(u.identifier),
            "identifier": u.identifier,
            "display_name": u.display_name or u.identifier,
            "email": u.email,
            "metadata": meta,
        }


# --- Public auth-status endpoint (no token) ---------------------------------


def admin_password_auth_enabled() -> bool:
    """Auth admin: di default sempre attiva (stile Grafana).

    Override con ``AION_ADMIN_PASSWORD_AUTH=0`` per disabilitare in dev.
    """
    raw = (os.getenv("AION_ADMIN_PASSWORD_AUTH") or "1").strip().lower()
    return raw in ("1", "true", "yes")


@router.get("/status")
async def auth_status():
    """Stato dell'autenticazione chat + admin. Usato dal frontend per
    decidere se forzare il redirect verso /login. Sempre pubblico."""

    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()

    # Leggi impostazioni login_mode (§3.1)
    login_mode = "password"
    sso_origin = None
    sso_migration_active = False
    password_login_vis = True
    sso_enabled = False
    sso_provider = None

    try:
        from src.auth.sso.login_mode import (
            get_login_settings,
            password_login_visible,
        )
        settings = await get_login_settings(tenant)
        login_mode = settings["login_mode"]
        sso_origin = settings["sso_origin"]
        sso_migration_active = (
            sso_origin == "migration"
            and not settings.get("migration_completed_at")
        )
        password_login_vis = await password_login_visible(tenant)
        if login_mode != "password":
            sso_enabled = True
            sso_provider = login_mode
    except Exception as _e:
        logger.warning("auth_status SSO check failed: %s", _e)
        # Fallback al comportamento precedente
        from src.auth.sso.config_service import public_view
        sso_config = await public_view(tenant)
        if sso_config and sso_config.get("enabled") and sso_config.get("validated_at"):
            if password_auth_enabled():
                sso_enabled = True
                sso_provider = sso_config.get("provider")

    # AION_SSO_FORCE_PASSWORD: bypass di emergenza (vedi §5)
    if (os.getenv("AION_SSO_FORCE_PASSWORD") or "").strip() == "1":
        login_mode = "password"
        sso_enabled = False
        sso_provider = None
        sso_migration_active = False
        password_login_vis = True

    return {
        "password_auth_enabled": password_auth_enabled(),
        "admin_password_auth_enabled": admin_password_auth_enabled(),
        "login_mode": login_mode,
        "sso_origin": sso_origin,
        "sso_migration_active": sso_migration_active,
        "password_login_visible": password_login_vis,
        "sso_enabled": sso_enabled,
        "sso_provider": sso_provider,
        "login_endpoint": "/auth/login",
        "token_ttl_seconds": _TOKEN_TTL_SEC,
        "first_setup_complete": os.getenv("AION_FIRST_SETUP_COMPLETE") == "1",
    }


# --- FastAPI dependency: require_chat_auth -----------------------------------


class ChatAuthIdentity(BaseModel):
    """Identita' propagata agli endpoint protetti."""

    user_row_id: Optional[str] = None
    identifier: Optional[str] = None
    via: str = "anonymous"  # "anonymous" | "chat_token" | "api_key"
    roles: List[str] = Field(default_factory=list)


# Lista di ruoli ottenuta dal contesto auth, gestendo i casi anonymous/api_key.
def _resolve_roles(ctx: "ChatAuthIdentity") -> List[str]:
    if ctx.via == "api_key":
        # Le API key con scope admin sono trattate come ruolo admin per il
        # router /admin/*. La via "anonymous" rispetta solo il bypass dev.
        return ctx.roles or []
    return ctx.roles or []


async def require_chat_auth(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    x_chat_ui_secret: Optional[str] = Header(None, alias="X-AION-Chat-Ui-Secret"),
    access_token: Optional[str] = Query(
        None,
        description="Token chat via query (per SSE via EventSource che non supporta header custom).",
    ),
) -> ChatAuthIdentity:
    """Protegge gli endpoint user-facing della chat.

    - Se ``AION_CHAT_PASSWORD_AUTH`` non e' attivo -> no-op (back-compat).
    - Altrimenti accetta uno dei seguenti:
        1. Bearer token emesso da ``/auth/login`` (token HMAC opaco) via
           ``Authorization`` header **oppure** query string ``?access_token=...``
           (necessario per gli endpoint SSE invocati via ``EventSource``).
        2. API key (header ``X-Api-Key`` o ``Authorization: Bearer aion_...``).
        3. ``X-AION-Chat-Ui-Secret`` valido (server-to-server, per il
           Next.js BFF del chat-ui).
    """
    # 1. Auth NON richiesta -> identita' anonima (modalita' default user).
    if not password_auth_enabled():
        return ChatAuthIdentity(via="anonymous")

    # 2. Secret interno chat-ui (BFF) -> bypass legittimo (trusted server-to-server).
    expected_internal = (os.getenv("AION_CHAT_UI_INTERNAL_SECRET") or "").strip()
    if expected_internal and (x_chat_ui_secret or "").strip() == expected_internal:
        return ChatAuthIdentity(
            via="api_key",
            identifier="chat-ui-internal",
            roles=["admin"],
        )

    # 3. Token Bearer (header), API key (header) o query token (SSE).
    token_raw = (x_api_key or "").strip()
    if not token_raw and authorization and authorization.lower().startswith("bearer "):
        token_raw = authorization.split(" ", 1)[1].strip()
    if not token_raw and access_token:
        token_raw = access_token.strip()

    if not token_raw:
        raise HTTPException(
            401,
            detail=(
                "Authentication required (AION_CHAT_PASSWORD_AUTH=1). "
                "POST /auth/login per ottenere un token, "
                "poi invia 'Authorization: Bearer <token>' o '?access_token=...' per SSE."
            ),
        )

    # API key (prefisso aion_) -> riusa il flusso esistente con le scope.
    if _looks_like_api_key(token_raw):
        try:
            from src.api.auth.dependencies import require_auth as _api_require_auth
            from src.api.auth.scopes import Scope as _Scope

            ctx = await _api_require_auth(
                authorization=f"Bearer {token_raw}", x_api_key=token_raw
            )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("API-key auth fallback failed: %s", e)
            raise HTTPException(401, detail="Invalid API key") from None
        # Mappa lo scope "admin" sulle API key in ruolo "admin" del modello user.
        api_scopes = list(getattr(ctx, "scopes", []) or [])
        api_roles = ["admin"] if _Scope.ADMIN in api_scopes else []
        return ChatAuthIdentity(
            via="api_key",
            identifier=getattr(ctx, "api_key_id", None),
            roles=api_roles,
        )

    # Token chat (HMAC opaco).
    parsed = verify_chat_token(token_raw)
    if not parsed:
        raise HTTPException(
            401, detail="Invalid or expired token. Re-login at /auth/login."
        )

    auth_identity = ChatAuthIdentity(
        via="chat_token",
        user_row_id=parsed.get("user_row_id"),
        identifier=parsed.get("identifier"),
        roles=parsed.get("roles") or [],
    )

    # Fix 0.4 / §3.6: blocco sso_link_required per token chat.
    # Le API key e il BFF passano senza questo controllo.
    user_row_id = parsed.get("user_row_id")
    if user_row_id:
        try:
            from src.auth.sso.login_mode import user_needs_link
            tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()
            needs_link = await user_needs_link(tenant, user_row_id)
            if needs_link:
                raise HTTPException(
                    403,
                    detail={"code": "sso_link_required"},
                )
        except HTTPException:
            raise
        except Exception as _e:
            logger.warning("SSO link check failed in require_chat_auth: %s", _e)

    return auth_identity


# --- Admin role guard -------------------------------------------------------


async def require_admin_role(
    ctx: ChatAuthIdentity = Depends(require_chat_auth),
) -> ChatAuthIdentity:
    """Guard per ``/admin/*``: richiede ruolo ``admin``.

    - Se ``AION_ADMIN_PASSWORD_AUTH=0`` (escape-hatch dev) e nessun token e'
      stato fornito, ``ctx.via == "anonymous"`` (vedi ``require_chat_auth``)
      e il check viene saltato.
    - Se ``AION_ADMIN_PASSWORD_AUTH=1`` (default): l'utente DEVE essere
      autenticato (un Bearer token e' richiesto da ``require_chat_auth``) E
      avere il ruolo ``admin``.
    """
    if not admin_password_auth_enabled():
        return ctx

    if ctx.via == "anonymous":
        # Nessun token presentato: ma password_auth chat era disattivata.
        # Forziamo qui l'autenticazione perche' il pannello admin va comunque
        # protetto secondo la policy "sempre attiva".
        raise HTTPException(
            401,
            detail=(
                "Admin authentication required. POST /auth/login per ottenere un "
                "token, poi invia 'Authorization: Bearer <token>'."
            ),
        )

    if "admin" not in (ctx.roles or []):
        raise HTTPException(403, detail="Admin role required")
    return ctx


# --- Change password (richiede token valido) --------------------------------


class ChangePasswordBody(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=512)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordBody,
    authorization: Optional[str] = Header(None),
):
    """Cambia la password dell'utente loggato.

    Verifica la vecchia password (bcrypt), salva la nuova hashata e azzera
    il flag ``must_change_password``.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    parsed = verify_chat_token(token)
    if not parsed:
        raise HTTPException(401, detail="Invalid or expired token")

    user_row_id = parsed["user_row_id"]

    from src.data.engine import get_async_session_maker
    from src.data.models import User
    from src.data.user_password import hash_password, verify_password

    async with get_async_session_maker()() as session:
        u = await session.get(User, user_row_id)
        if not u or not u.password_hash:
            raise HTTPException(404, detail="User not found or password not set")
        if not verify_password(body.old_password, u.password_hash):
            raise HTTPException(401, detail="Old password is wrong")
        if body.new_password == body.old_password:
            raise HTTPException(400, detail="New password must differ from the old one")
        u.password_hash = hash_password(body.new_password)
        u.must_change_password = False
        session.add(u)
        await session.commit()

    return {"status": "ok", "must_change_password": False}
