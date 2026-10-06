"""SSO provider descriptors."""

from dataclasses import dataclass
from typing import List, Optional

@dataclass
class SsoProviderDescriptor:
    provider_id: str
    authorize_url: str
    token_url: str
    jwks_url: str
    issuer_template: str
    default_scopes: List[str]

MICROSOFT = SsoProviderDescriptor(
    provider_id="microsoft",
    authorize_url="https://login.microsoftonline.com/{tid}/oauth2/v2.0/authorize",
    token_url="https://login.microsoftonline.com/{tid}/oauth2/v2.0/token",
    jwks_url="https://login.microsoftonline.com/{tid}/discovery/v2.0/keys",
    issuer_template="https://login.microsoftonline.com/{tid}/v2.0",
    default_scopes=["openid", "profile", "email", "offline_access"]
)

GOOGLE = SsoProviderDescriptor(
    provider_id="google",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    jwks_url="https://www.googleapis.com/oauth2/v3/certs",
    issuer_template="https://accounts.google.com",
    default_scopes=["openid", "email", "profile"]
)

def get_descriptor(provider_id: str) -> Optional[SsoProviderDescriptor]:
    if provider_id == "microsoft":
        return MICROSOFT
    if provider_id == "google":
        return GOOGLE
    return None
