from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.data.engine import get_async_session_maker
from src.data.models import LlmProvider

router = APIRouter(prefix="/llm-providers", tags=["v1-llm-providers"])


class LlmProviderChatPublic(BaseModel):
    slug: str
    display_name: str
    model_name: str
    description: Optional[str] = None
    icon_url: Optional[str] = None
    is_default: bool
    enabled: bool


@router.get("", response_model=List[LlmProviderChatPublic])
async def list_enabled_llm_providers(
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    tenant_id: str = "default",
):
    """Restituisce i provider LLM abilitati (lettura sicura per utenti chat)."""
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(LlmProvider)
                    .where(
                        LlmProvider.tenant_id == tenant_id,
                        LlmProvider.enabled == True,
                    )
                    .order_by(LlmProvider.is_default.desc(), LlmProvider.display_name)
                )
            )
            .scalars()
            .all()
        )
    return [
        LlmProviderChatPublic(
            slug=r.slug,
            display_name=r.display_name,
            model_name=r.model_name,
            description=r.description,
            icon_url=r.icon_url,
            is_default=r.is_default,
            enabled=r.enabled,
        )
        for r in rows
    ]
