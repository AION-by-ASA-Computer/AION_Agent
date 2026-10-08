"""SSO API router for auth frontend.

Fix 0.2: /auth/sso/start public accetta SOLO purpose=login.
Fix 0.3: admin_validate collega l'identità all'admin e usa user_id reale.
Fix 0.4: handoff code invece di token nel fragment.
Fix 0.5: redirect errori → {chat_base}/login?error=…
Fix 0.6: user_id calcolato lato server, non decodificato dal client.
"""

import hashlib
import html
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, update

from src.api.auth_login import (
    ChatAuthIdentity,
    issue_chat_token,
    require_chat_token_only,
)
from src.api.public_urls import admin_base_url, chat_base_url, oauth_redirect_api_base
from src.auth.sso.config_service import get_provider, mark_validated
from src.auth.sso.flow import build_authorize_url, handle_callback
from src.auth.sso.id_token import verify_id_token
from src.auth.sso.provisioning import link_identity_to_user, resolve_user
from src.data.engine import get_async_session_maker
from src.data.ids import new_uuid7_str
from src.data.models import SsoAuthState
from src.identity import sanitize_user_id
from src.runtime.credential_store import decrypt_value, encrypt_value

logger = logging.getLogger("aion.api.auth_sso")
router = APIRouter(prefix="/auth/sso", tags=["auth_sso"])

_HANDOFF_TTL_SEC = 60


def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


def _get_redirect_uri(request: Request) -> str:
    base = oauth_redirect_api_base(request).rstrip("/")
    return f"{base}/auth/sso/callback"


def _validate_return_to(return_to: Optional[str]) -> str:
    """Valida return_to: accetta solo path relativi."""
    rt = (return_to or "/").strip()
    if rt.startswith("http://") or rt.startswith("https://"):
        return "/"
    if not rt.startswith("/"):
        return "/"
    return rt


async def _create_handoff_code(
    payload: dict,
    tenant_id: str,
) -> str:
    """Crea un handoff code monouso con TTL 60s cifrato in sso_auth_states."""
    import json

    code_raw = secrets.token_urlsafe(32)
    code_hash = hashlib.sha256(code_raw.encode("ascii")).hexdigest()
    payload_json = json.dumps(payload)
    payload_encrypted = encrypt_value(payload_json)

    async with get_async_session_maker()() as session:
        now = datetime.now(timezone.utc)
        session.add(
            SsoAuthState(
                state_hash=code_hash,
                kind="handoff",
                purpose="exchange",
                provider=payload.get("provider", ""),
                nonce=None,
                code_verifier_encrypted=None,
                user_id=payload.get("user_id"),
                return_to=payload.get("return_to", "/"),
                payload_json=payload_encrypted,
                expires_at=now + timedelta(seconds=_HANDOFF_TTL_SEC),
            )
        )
        await session.commit()

    return code_raw


# ---------------------------------------------------------------------------
# Public endpoint: solo purpose=login (fix 0.2)
# ---------------------------------------------------------------------------

@router.get("/start")
async def sso_start(
    request: Request,
    provider: str,
    return_to: str = "/",
    client: str = "chat",
):
    """Avvia il flusso SSO per il login. Accetta SOLO purpose=login
    (``client=admin`` → ``admin_login``: stesso login, ritorno su admin-ui).

    I purpose privilegiati (link, admin_validate) partono da endpoint
    autenticati separati.
    """
    return_to = _validate_return_to(return_to)
    is_admin = client == "admin"

    try:
        url = await build_authorize_url(
            provider=provider,
            purpose="admin_login" if is_admin else "login",
            return_to=return_to,
            redirect_uri=_get_redirect_uri(request),
            tenant_id=_tenant_id(),
            user_id=None,
        )
        return RedirectResponse(url)
    except Exception as e:
        logger.warning("Error starting SSO login: %s", e)
        base = (admin_base_url(request) if is_admin else chat_base_url(request)).rstrip("/")
        return RedirectResponse(f"{base}/login?error=sso_start_failed")


# ---------------------------------------------------------------------------
# Authenticated endpoint per link (fix 0.2)
# ---------------------------------------------------------------------------

class LinkStartBody(BaseModel):
    return_to: Optional[str] = "/"


@router.post("/link/start")
async def sso_link_start(
    request: Request,
    body: LinkStartBody,
    auth: ChatAuthIdentity = Depends(require_chat_token_only),
):
    """Avvia il flusso SSO di collegamento. Richiede token chat utente.

    Usa require_chat_token_only: senza il blocco sso_link_required (l'utente
    deve poter avviare il link proprio quando e' in stato link_required).
    Solo token HMAC utente: API key / BFF non hanno un utente da collegare.
    """
    if auth.via != "chat_token" or not auth.user_row_id:
        raise HTTPException(401, detail="Token utente richiesto")

    # Recupera il provider attivo
    from src.auth.sso.config_service import get_active_provider
    config = await get_active_provider(_tenant_id())
    if not config:
        raise HTTPException(400, detail={"code": "sso_not_configured"})

    return_to = _validate_return_to(body.return_to)
    try:
        url = await build_authorize_url(
            provider=config["provider"],
            purpose="link",
            return_to=return_to,
            redirect_uri=_get_redirect_uri(request),
            tenant_id=_tenant_id(),
            user_id=auth.user_row_id,
        )
        return {"authorize_url": url}
    except Exception as e:
        logger.warning("Error starting SSO link: %s", e)
        raise HTTPException(400, detail=str(e))


# ---------------------------------------------------------------------------
# Callback unificato
# ---------------------------------------------------------------------------

@router.get("/callback")
async def sso_callback(
    request: Request,
    code: str,
    state: str,
):
    chat_base = chat_base_url(request).rstrip("/")

    try:
        data = await handle_callback(
            code=code,
            state_raw=state,
            redirect_uri=_get_redirect_uri(request),
            tenant_id=_tenant_id(),
        )
    except Exception as e:
        logger.warning("SSO Callback error: %s", e)
        return RedirectResponse(f"{chat_base}/login?error=sso_failed")

    provider_config = data["provider_config"]
    try:
        claims = verify_id_token(
            id_token=data["id_token"],
            provider_config=provider_config,
            expected_nonce=data["nonce"],
        )
    except Exception as e:
        logger.warning("SSO ID Token error: %s", e)
        return RedirectResponse(f"{chat_base}/login?error=sso_token_invalid")

    purpose = data.get("purpose", "login")

    # -----------------------------------------------------------------------
    # admin_validate: collega identità all'admin e segna il provider validato
    # (fix 0.3)
    # -----------------------------------------------------------------------
    if purpose == "admin_validate":
        target_user_id = data.get("target_user_id")
        if not target_user_id:
            logger.warning("admin_validate senza user_id nel state")
            return HTMLResponse(
                "<h3>Errore: sessione non valida. Riprova.</h3>",
                status_code=400,
            )
        try:
            # Collega l'identità SSO all'admin (o aggiorna se idempotente)
            await link_identity_to_user(
                tenant_id=_tenant_id(),
                user_id=target_user_id,
                claims=claims,
                token_data=data,
                provider_config=provider_config,
            )
            await mark_validated(
                tenant_id=_tenant_id(),
                provider=provider_config["provider"],
                user_id=target_user_id,
            )
        except Exception as e:
            logger.warning("Admin validate error: %s", e)
            return HTMLResponse(
                f"<h3>Errore durante la validazione</h3><p>{html.escape(str(e))}</p>",
                status_code=400,
            )

        # postMessage al pannello admin + autoclose
        admin_origin = (os.getenv("AION_ADMIN_URL") or "").rstrip("/")
        return HTMLResponse(
            f"""<!doctype html>
<html>
<head><title>Verifica SSO</title></head>
<body>
  <h3>Verifica completata con successo.</h3>
  <p>Puoi chiudere questa finestra e tornare ad AION.</p>
  <script>
    try {{
      var origin = {repr(admin_origin) if admin_origin else '\"*\"'};
      if (window.opener) {{
        window.opener.postMessage({{type: "aion-sso-validated"}}, origin);
      }}
    }} catch(e) {{}}
    setTimeout(function() {{ window.close(); }}, 2000);
  </script>
</body>
</html>"""
        )

    # -----------------------------------------------------------------------
    # link: collega identità a utente già autenticato (fix 0.2, 0.4)
    # -----------------------------------------------------------------------
    if purpose == "link":
        target_user_id = data.get("target_user_id")
        if not target_user_id:
            return RedirectResponse(f"{chat_base}/?sso_link_error=session_invalid")
        try:
            await link_identity_to_user(
                tenant_id=_tenant_id(),
                user_id=target_user_id,
                claims=claims,
                token_data=data,
                provider_config=provider_config,
                finalize_migration=True,
            )
        except ValueError as e:
            error_code = str(e)
            logger.warning("SSO link error for user %s: %s", target_user_id, error_code)
            return RedirectResponse(
                f"{chat_base}/?sso_link_error={quote(error_code, safe='')}"
            )
        except Exception as e:
            logger.exception("Unexpected SSO link error: %s", e)
            return RedirectResponse(f"{chat_base}/?sso_link_error=link_failed")

        # Recupera dati utente per emettere un nuovo token
        from src.data.models import User
        from src.data.user_password import get_roles

        async with get_async_session_maker()() as session:
            user = await session.get(User, target_user_id)

        if not user:
            return RedirectResponse(f"{chat_base}/?sso_link_error=user_not_found")

        roles = get_roles(user)
        tok = issue_chat_token(
            user_row_id=user.id,
            user_identifier=user.identifier,
            roles=roles,
        )
        uid = sanitize_user_id(user.identifier)
        return_to = _validate_return_to(data.get("return_to"))

        # Handoff code (fix 0.4)
        handoff_payload = {
            "access_token": tok,
            "user_id": uid,
            "identifier": user.identifier,
            "display_name": user.display_name or user.identifier,
            "roles": roles,
            "sso_link_required": False,
            "provider": provider_config["provider"],
            "return_to": return_to,
        }
        code_raw = await _create_handoff_code(handoff_payload, _tenant_id())
        return RedirectResponse(
            f"{chat_base}/login/sso#code={quote(code_raw, safe='')}&return_to={quote(return_to, safe='/')}"
        )

    # -----------------------------------------------------------------------
    # admin_login: login SSO dal pannello admin. Solo utenti esistenti con
    # ruolo admin (niente auto-provisioning), ritorno su admin-ui.
    # -----------------------------------------------------------------------
    if purpose == "admin_login":
        admin_base = admin_base_url(request).rstrip("/")
        try:
            from src.auth.sso.login_mode import is_migration_active

            user_dict = await resolve_user(
                claims=claims,
                token_data=data,
                provider_config={**provider_config, "auto_provision": False},
                tenant_id=_tenant_id(),
                migration_active=await is_migration_active(_tenant_id()),
            )
        except ValueError as e:
            error_code = str(e)
            logger.warning("SSO admin login error: %s", error_code)
            return RedirectResponse(f"{admin_base}/login?error={quote(error_code, safe='')}")
        except Exception as e:
            logger.exception("Unexpected SSO admin login error: %s", e)
            return RedirectResponse(f"{admin_base}/login?error=sso_failed")

        roles = list(user_dict.get("roles") or [])
        if "admin" not in roles:
            return RedirectResponse(f"{admin_base}/login?error=not_admin")
        tok = issue_chat_token(
            user_row_id=str(user_dict["id"]),
            user_identifier=str(user_dict["identifier"]),
            roles=roles,
        )
        return_to = _validate_return_to(data.get("return_to"))
        handoff_payload = {
            "access_token": tok,
            "user_id": sanitize_user_id(str(user_dict["identifier"])),
            "identifier": str(user_dict["identifier"]),
            "display_name": str(user_dict.get("display_name") or user_dict["identifier"]),
            "roles": roles,
            "sso_link_required": False,
            "provider": provider_config["provider"],
            "return_to": return_to,
        }
        code_raw = await _create_handoff_code(handoff_payload, _tenant_id())
        return RedirectResponse(
            f"{admin_base}/login/sso#code={quote(code_raw, safe='')}&return_to={quote(return_to, safe='/')}"
        )

    # -----------------------------------------------------------------------
    # login normale (fix 0.4, 0.5, 0.6)
    # -----------------------------------------------------------------------
    try:
        from src.auth.sso.login_mode import is_migration_active

        user_dict = await resolve_user(
            claims=claims,
            token_data=data,
            provider_config=provider_config,
            tenant_id=_tenant_id(),
            migration_active=await is_migration_active(_tenant_id()),
        )
    except ValueError as e:
        error_code = str(e)
        logger.warning("SSO resolve_user error: %s", error_code)
        return RedirectResponse(f"{chat_base}/login?error={quote(error_code, safe='')}")
    except Exception as e:
        logger.exception("Unexpected SSO provisioning error: %s", e)
        return RedirectResponse(f"{chat_base}/login?error=sso_provisioning_failed")

    roles = list(user_dict.get("roles") or [])
    tok = issue_chat_token(
        user_row_id=str(user_dict["id"]),
        user_identifier=str(user_dict["identifier"]),
        roles=roles,
    )
    # user_id calcolato lato server (fix 0.6)
    uid = sanitize_user_id(str(user_dict["identifier"]))
    return_to = _validate_return_to(data.get("return_to"))

    # Handoff code invece di token nel fragment (fix 0.4)
    handoff_payload = {
        "access_token": tok,
        "user_id": uid,
        "identifier": str(user_dict["identifier"]),
        "display_name": str(user_dict.get("display_name") or user_dict["identifier"]),
        "roles": roles,
        "sso_link_required": False,
        "provider": provider_config["provider"],
        "return_to": return_to,
    }
    code_raw = await _create_handoff_code(handoff_payload, _tenant_id())
    return RedirectResponse(
        f"{chat_base}/login/sso#code={quote(code_raw, safe='')}&return_to={quote(return_to, safe='/')}"
    )


# ---------------------------------------------------------------------------
# Exchange: monouso, TTL 60s, restituisce il token (fix 0.4)
# ---------------------------------------------------------------------------

class ExchangeBody(BaseModel):
    code: str


@router.post("/exchange")
async def sso_exchange(body: ExchangeBody):
    """Scambia un handoff code con access_token. Monouso, TTL 60s."""
    import json

    code_hash = hashlib.sha256(body.code.encode("ascii")).hexdigest()
    now = datetime.now(timezone.utc)

    async with get_async_session_maker()() as session:
        state = (
            await session.execute(
                select(SsoAuthState).where(SsoAuthState.state_hash == code_hash)
            )
        ).scalars().first()

        if not state or state.kind != "handoff":
            raise HTTPException(400, detail={"code": "invalid_code"})
        if state.consumed_at:
            raise HTTPException(400, detail={"code": "code_already_used"})

        expires_at = state.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < now:
            raise HTTPException(400, detail={"code": "code_expired"})

        encrypted_payload = state.payload_json

        # Consumo atomico: due richieste concorrenti con lo stesso codice non
        # possono riuscire entrambe (UPDATE condizionato su consumed_at IS NULL).
        res = await session.execute(
            update(SsoAuthState)
            .where(
                SsoAuthState.state_hash == code_hash,
                SsoAuthState.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        await session.commit()
        if res.rowcount != 1:
            raise HTTPException(400, detail={"code": "code_already_used"})

    try:
        payload_json = decrypt_value(encrypted_payload)
        payload = json.loads(payload_json)
    except Exception:
        raise HTTPException(500, detail={"code": "exchange_error"})

    return {
        "access_token": payload["access_token"],
        "token_type": "bearer",
        "user_id": payload["user_id"],
        "identifier": payload.get("identifier"),
        "display_name": payload.get("display_name"),
        "roles": payload.get("roles", []),
        "sso_link_required": payload.get("sso_link_required", False),
    }
