"""SSO API router for auth frontend."""

import os
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse

from src.api.public_urls import oauth_redirect_api_base, chat_base_url
from src.auth.sso.flow import build_authorize_url, handle_callback
from src.auth.sso.id_token import verify_id_token
from src.auth.sso.provisioning import resolve_user
from src.auth.sso.config_service import mark_validated
from src.api.auth_login import issue_chat_token
from src.chat_auth import password_auth_enabled

logger = logging.getLogger("aion.api.auth_sso")
router = APIRouter(prefix="/auth/sso", tags=["auth_sso"])

def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()

def _get_redirect_uri(request: Request) -> str:
    base = oauth_redirect_api_base(request).rstrip("/")
    return f"{base}/v1/auth/sso/callback"

@router.get("/start")
async def sso_start(
    request: Request,
    provider: str,
    return_to: str = "/",
    purpose: str = "login",
    target_user_id: Optional[str] = None,
):
    """Redirige l'utente alla pagina di login del provider."""
    if return_to.startswith("http://") or return_to.startswith("https://"):
        return_to = "/"

    try:
        url = await build_authorize_url(
            provider=provider,
            purpose=purpose,
            return_to=return_to,
            redirect_uri=_get_redirect_uri(request),
            tenant_id=_tenant_id(),
            user_id=target_user_id,
        )
        return RedirectResponse(url)
    except Exception as e:
        logger.exception("Error starting SSO")
        raise HTTPException(400, detail=str(e))

@router.get("/callback")
async def sso_callback(
    request: Request,
    code: str,
    state: str,
):
    try:
        data = await handle_callback(
            code=code,
            state_raw=state,
            redirect_uri=_get_redirect_uri(request),
            tenant_id=_tenant_id()
        )
    except Exception as e:
        logger.warning(f"SSO Callback error: {e}")
        return RedirectResponse("/login?error=sso_failed")

    try:
        claims = verify_id_token(
            id_token=data["id_token"],
            provider_config=data["provider_config"],
            expected_nonce=data["nonce"]
        )
    except Exception as e:
        logger.warning(f"SSO ID Token error: {e}")
        return RedirectResponse("/login?error=sso_token_invalid")

    purpose = data.get("purpose", "login")
    if purpose == "admin_validate":
        try:
            await mark_validated(
                tenant_id=_tenant_id(),
                provider=data["provider_config"]["provider"],
                user_id=data.get("target_user_id", "admin")
            )
            return HTMLResponse("""
                <html>
                <body>
                    <h3>Verifica completata con successo.</h3>
                    <p>Puoi chiudere questa finestra e tornare ad AION.</p>
                    <script>
                        setTimeout(() => window.close(), 3000);
                    </script>
                </body>
                </html>
            """)
        except Exception as e:
            logger.warning(f"Admin validate error: {e}")
            return HTMLResponse(f"<h3>Errore durante la validazione</h3><p>{str(e)}</p>")

    # Normal login
    try:
        user_dict = await resolve_user(
            claims=claims,
            token_data=data,
            provider_config=data["provider_config"],
            tenant_id=_tenant_id()
        )
    except Exception as e:
        logger.warning(f"SSO Provisioning error: {e}")
        return RedirectResponse("/login?error=sso_provisioning_failed")

    roles = list(user_dict.get("roles") or [])
    tok = issue_chat_token(
        user_row_id=str(user_dict["id"]),
        user_identifier=str(user_dict["identifier"]),
        roles=roles,
    )
    
    return_to = data.get("return_to", "/")
    chat_base = chat_base_url(request).rstrip("/")
    redirect_target = f"{chat_base}/login#sso_token={tok}&return_to={return_to}"
    return RedirectResponse(redirect_target)
