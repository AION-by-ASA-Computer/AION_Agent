"""SSO OAuth Flow helpers."""

import base64
import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from sqlalchemy import select

from src.auth.sso.config_service import get_active_provider, get_provider
from src.auth.sso.providers import get_descriptor
from src.data.engine import get_async_session_maker
from src.data.models import SsoAuthState
from src.runtime.credential_store import encrypt_value, decrypt_value
from src.runtime.oauth_token_exchange import exchange_authorization_code

logger = logging.getLogger("aion.sso.flow")


def _generate_pkce_pair() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


async def build_authorize_url(
    provider: str,
    purpose: str,
    return_to: str,
    redirect_uri: str,
    tenant_id: str = "default",
    user_id: Optional[str] = None,
) -> str:
    # admin_validate può partire anche prima che il provider sia abilitato (fix 0.1).
    require_enabled = purpose not in ("admin_validate",)
    config = await get_provider(tenant_id, provider, require_enabled=require_enabled)
    if not config:
        raise ValueError("SSO non configurato o disabilitato.")

    descriptor = get_descriptor(provider)
    if not descriptor:
        raise ValueError(f"Provider {provider} non supportato.")

    state_raw = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state_raw.encode("ascii")).hexdigest()
    nonce = secrets.token_urlsafe(16)
    code_verifier, code_challenge = _generate_pkce_pair()

    async with get_async_session_maker()() as session:
        now = datetime.now(timezone.utc)
        session.add(
            SsoAuthState(
                state_hash=state_hash,
                kind="authorize",
                purpose=purpose,
                provider=provider,
                nonce=nonce,
                code_verifier_encrypted=encrypt_value(code_verifier),
                user_id=user_id,
                return_to=return_to,
                expires_at=now + timedelta(minutes=10),
            )
        )
        await session.commit()

    tid = config.get("directory_tenant_id") or "common"
    auth_url = descriptor.authorize_url.replace("{tid}", tid)

    params = {
        "client_id": config["client_id"],
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(descriptor.default_scopes),
        "state": state_raw,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }

    # Provider-specific tweaks
    if provider == "google" and config.get("allowed_domains"):
        params["hd"] = config["allowed_domains"][0]

    return f"{auth_url}?{urlencode(params)}"


async def handle_callback(
    code: str,
    state_raw: str,
    redirect_uri: str,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    state_hash = hashlib.sha256(state_raw.encode("ascii")).hexdigest()
    now = datetime.now(timezone.utc)

    async with get_async_session_maker()() as session:
        auth_state = (
            (
                await session.execute(
                    select(SsoAuthState).where(SsoAuthState.state_hash == state_hash)
                )
            )
            .scalars()
            .first()
        )

        if not auth_state:
            raise ValueError("state_invalid")
        if auth_state.consumed_at:
            raise ValueError("state_invalid")
            
        expires_at = auth_state.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
            
        if expires_at < now:
            raise ValueError("state_invalid")

        auth_state.consumed_at = now
        await session.commit()

        provider = auth_state.provider
        purpose = auth_state.purpose
        return_to = auth_state.return_to
        nonce = auth_state.nonce
        code_verifier = decrypt_value(auth_state.code_verifier_encrypted) if auth_state.code_verifier_encrypted else None
        target_user_id = auth_state.user_id

    # Per admin_validate il provider potrebbe non essere ancora abilitato (fix 0.1).
    config = await get_provider(tenant_id, provider, require_enabled=False)
    if not config:
        raise ValueError("provider_error")

    descriptor = get_descriptor(provider)
    if not descriptor:
        raise ValueError("provider_error")

    tid = config.get("directory_tenant_id") or "common"
    token_url = descriptor.token_url.replace("{tid}", tid)

    # exchange_authorization_code takes code_verifier, client_id, client_secret
    token_data = await exchange_authorization_code(
        token_url=token_url,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        client_id=config["client_id"],
        client_secret=config["client_secret"],
    )

    id_token = token_data.get("id_token")
    if not id_token:
        raise ValueError("provider_error")

    return {
        "id_token": id_token,
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data.get("expires_in"),
        "nonce": nonce,
        "purpose": purpose,
        "return_to": return_to,
        "target_user_id": target_user_id,
        "provider_config": config,
    }
