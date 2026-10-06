"""SSO User Provisioning and resolution."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import select

from src.chat_auth import _user_to_auth_dict
from src.data.engine import get_async_session_maker
from src.data.ids import new_uuid7_str
from src.data.models import User, UserSsoIdentity
from src.runtime.credential_store import encrypt_value

logger = logging.getLogger("aion.sso.provisioning")


async def resolve_user(
    claims: Dict[str, Any],
    token_data: Dict[str, Any],
    provider_config: Dict[str, Any],
    tenant_id: str = "default",
) -> Dict[str, Any]:
    provider = provider_config["provider"]
    
    # 1. Determine Subject and Email
    if provider == "microsoft":
        tid = claims.get("tid")
        oid = claims.get("oid")
        if not tid or not oid:
            raise ValueError("missing_subject_claims")
        subject = f"{tid}:{oid}"
        email = claims.get("preferred_username") or claims.get("email")
    elif provider == "google":
        subject = claims.get("sub")
        if not subject:
            raise ValueError("missing_subject_claims")
        email = claims.get("email")
    else:
        raise ValueError("unsupported_provider")

    email = (email or "").strip().lower()
    display_name = claims.get("name") or claims.get("given_name") or email

    now = datetime.now(timezone.utc)
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in")
    token_expires_at = now + timedelta(seconds=expires_in) if expires_in else None
    
    # Use encrypt_value securely
    access_token_encrypted = encrypt_value(access_token) if access_token else None

    async with get_async_session_maker()() as session:
        # 1. Find existing identity
        identity = (
            (
                await session.execute(
                    select(UserSsoIdentity).where(
                        UserSsoIdentity.tenant_id == tenant_id,
                        UserSsoIdentity.provider == provider,
                        UserSsoIdentity.subject == subject,
                    )
                )
            )
            .scalars()
            .first()
        )

        user = None
        if identity:
            user = (
                (
                    await session.execute(
                        select(User).where(User.id == identity.user_id)
                    )
                )
                .scalars()
                .first()
            )

        if not user and email:
            # 2. Try linking by email
            matching_users = (
                (
                    await session.execute(
                        select(User).where(
                            User.tenant_id == tenant_id,
                            (User.email.ilike(email)) | (User.identifier.ilike(email))
                        )
                    )
                )
                .scalars()
                .all()
            )
            
            # Link only if exactly one matches
            if len(matching_users) == 1:
                user = matching_users[0]
                logger.info(f"Linked SSO identity {subject} to existing user {user.id} by email")
        
        if not user:
            # 3. Auto provision
            if not provider_config.get("auto_provision", True):
                raise ValueError("sso_user_not_allowed")

            if not email:
                raise ValueError("email_required_for_provisioning")

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
            logger.info(f"Auto-provisioned new SSO user {user_id}")

        # Update last active
        user.last_active_at = now

        # Upsert identity
        if identity:
            identity.access_token_encrypted = access_token_encrypted
            identity.token_expires_at = token_expires_at
            identity.last_login_at = now
            identity.updated_at = now
            identity.email = email
            identity.display_name = display_name
        else:
            identity = UserSsoIdentity(
                id=new_uuid7_str(),
                tenant_id=tenant_id,
                user_id=user.id,
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
            session.add(identity)

        await session.commit()
        await session.refresh(user)

    return _user_to_auth_dict(user)
