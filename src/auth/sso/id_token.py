"""SSO ID Token validation."""

import logging
from typing import Any, Dict

import jwt
from jwt import PyJWKClient

from src.auth.sso.providers import get_descriptor

logger = logging.getLogger("aion.sso.id_token")

# Maintain a cache of JWK clients per URL
_JWK_CLIENTS: Dict[str, PyJWKClient] = {}

def get_jwks_client(url: str) -> PyJWKClient:
    if url not in _JWK_CLIENTS:
        _JWK_CLIENTS[url] = PyJWKClient(url, cache_keys=True, cache_jwk_set=True, lifespan=3600)
    return _JWK_CLIENTS[url]

def verify_id_token(
    id_token: str,
    provider_config: Dict[str, Any],
    expected_nonce: str,
) -> Dict[str, Any]:
    provider = provider_config["provider"]
    descriptor = get_descriptor(provider)
    if not descriptor:
        raise ValueError(f"Provider {provider} non supportato")

    tid = provider_config.get("directory_tenant_id") or "common"
    jwks_url = descriptor.jwks_url.replace("{tid}", tid)
    issuer = descriptor.issuer_template.replace("{tid}", tid)
    
    jwks_client = get_jwks_client(jwks_url)
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
    except Exception as e:
        logger.warning(f"Errore JWKS per {provider}: {e}")
        raise ValueError("token_signature_invalid") from e

    try:
        payload = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=provider_config["client_id"],
            issuer=issuer,
            leeway=60,
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT non valido per {provider}: {e}")
        raise ValueError("token_invalid") from e

    # Verify nonce
    if payload.get("nonce") != expected_nonce:
        raise ValueError("nonce_mismatch")

    # Provider specific checks
    if provider == "microsoft":
        if payload.get("tid") != provider_config.get("directory_tenant_id"):
            raise ValueError("tenant_mismatch")
        
        # Check domain if domains are allowed (optional for MS)
        allowed_domains = provider_config.get("allowed_domains", [])
        if allowed_domains:
            email = payload.get("preferred_username") or payload.get("email") or ""
            domain = email.split("@")[-1].lower() if "@" in email else ""
            allowed_domains_lower = [d.lower() for d in allowed_domains]
            if domain not in allowed_domains_lower:
                raise ValueError("domain_not_allowed")

    elif provider == "google":
        if str(payload.get("email_verified", "")).lower() not in ("true", "1"):
            # sometimes boolean, sometimes string
            if payload.get("email_verified") is not True:
                raise ValueError("email_not_verified")
            
        allowed_domains = provider_config.get("allowed_domains", [])
        if allowed_domains:
            hd = (payload.get("hd") or "").lower()
            allowed_domains_lower = [d.lower() for d in allowed_domains]
            if hd not in allowed_domains_lower:
                raise ValueError("domain_not_allowed")

    return payload
