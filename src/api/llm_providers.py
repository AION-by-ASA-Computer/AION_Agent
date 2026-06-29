"""Admin API: CRUD per LLM providers."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.data.engine import get_async_session_maker
from src.data.ids import new_uuid7_str
from src.data.models import LlmProvider
from src.runtime.credential_store import encrypt_value
from sqlalchemy import select, delete, update

logger = logging.getLogger("aion.api.llm_providers")

router = APIRouter(prefix="/llm-providers", tags=["admin-llm-providers"])

# --- Pydantic models ---

class LlmProviderCreate(BaseModel):
    slug: str
    display_name: str
    description: Optional[str] = None
    icon_url: Optional[str] = None
    provider: str = Field(..., description="openai, anthropic, google, etc.")
    model_name: str
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: int = 120
    max_chat_tokens: Optional[int] = None
    thinking_token_budget: Optional[int] = None
    enabled: bool = True
    is_default: bool = False
    metadata: Optional[Dict] = None

class LlmProviderUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon_url: Optional[str] = None
    provider: Optional[str] = None
    model_name: Optional[str] = None
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: Optional[int] = None
    max_chat_tokens: Optional[int] = None
    thinking_token_budget: Optional[int] = None
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None
    metadata: Optional[Dict] = None

class LlmProviderPublic(BaseModel):
    id: str
    slug: str
    display_name: str
    description: Optional[str] = None
    icon_url: Optional[str] = None
    provider: str
    model_name: str
    api_base_url: Optional[str] = None
    api_key_present: bool = False
    timeout: int
    max_chat_tokens: Optional[int] = None
    thinking_token_budget: Optional[int] = None
    enabled: bool
    is_default: bool
    metadata: Dict = Field(default_factory=dict)

# --- Endpoints ---

@router.get("", response_model=List[LlmProviderPublic])
async def list_llm_providers(tenant_id: str = "default"):
    """Lista tutti i provider LLM per tenant."""
    async with get_async_session_maker()() as session:
        rows = (await session.execute(
            select(LlmProvider)
            .where(LlmProvider.tenant_id == tenant_id)
            .order_by(LlmProvider.is_default.desc(), LlmProvider.display_name)
        )).scalars().all()
    return [
        LlmProviderPublic(
            id=r.id,
            slug=r.slug,
            display_name=r.display_name,
            description=r.description,
            icon_url=r.icon_url,
            provider=r.provider,
            model_name=r.model_name,
            api_base_url=r.api_base_url,
            api_key_present=bool(r.api_key_encrypted),
            timeout=r.timeout,
            max_chat_tokens=r.max_chat_tokens,
            thinking_token_budget=r.thinking_token_budget,
            enabled=r.enabled,
            is_default=r.is_default,
            metadata=json.loads(r.metadata_json or "{}"),
        )
        for r in rows
    ]

@router.get("/{slug}", response_model=LlmProviderPublic)
async def get_llm_provider(slug: str, tenant_id: str = "default"):
    """Ottieni un singolo provider LLM."""
    async with get_async_session_maker()() as session:
        row = (await session.execute(
            select(LlmProvider).where(
                LlmProvider.tenant_id == tenant_id,
                LlmProvider.slug == slug,
            )
        )).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="LLM provider not found")
    return LlmProviderPublic(
        id=row.id,
        slug=row.slug,
        display_name=row.display_name,
        description=row.description,
        icon_url=row.icon_url,
        provider=row.provider,
        model_name=row.model_name,
        api_base_url=row.api_base_url,
        api_key_present=bool(row.api_key_encrypted),
        timeout=row.timeout,
        max_chat_tokens=row.max_chat_tokens,
        thinking_token_budget=row.thinking_token_budget,
        enabled=row.enabled,
        is_default=row.is_default,
        metadata=json.loads(row.metadata_json or "{}"),
    )

@router.post("", response_model=LlmProviderPublic)
async def create_llm_provider(body: LlmProviderCreate):
    """Crea un nuovo provider LLM."""
    # Validazione: api_key obbligatoria se non è un provider built-in
    if body.provider not in ("openai", "anthropic", "google"):
        if not body.api_key:
            raise HTTPException(
                status_code=400,
                detail="API key required for third-party providers"
            )
    
    async with get_async_session_maker()() as session:
        # Controlla duplicato
        existing = (await session.execute(
            select(LlmProvider).where(
                LlmProvider.tenant_id == "default",
                LlmProvider.slug == body.slug,
            )
        )).scalars().first()
        if existing:
            raise HTTPException(status_code=409, detail="Provider with this slug already exists")
        
        # Se is_default=True, deseleziona gli altri
        if body.is_default:
            await session.execute(
                update(LlmProvider)
                .where(LlmProvider.tenant_id == "default")
                .values(is_default=False)
            )
        
        # Cripta l'API key
        api_key_encrypted = None
        if body.api_key:
            api_key_encrypted = encrypt_value(body.api_key)
        
        provider = LlmProvider(
            id=new_uuid7_str(),
            tenant_id="default",
            slug=body.slug,
            display_name=body.display_name,
            description=body.description,
            icon_url=body.icon_url,
            provider=body.provider,
            model_name=body.model_name,
            api_base_url=body.api_base_url,
            api_key_encrypted=api_key_encrypted,
            timeout=body.timeout,
            max_chat_tokens=body.max_chat_tokens,
            thinking_token_budget=body.thinking_token_budget,
            enabled=body.enabled,
            is_default=body.is_default,
            metadata_json=json.dumps(body.metadata or {}),
        )
        session.add(provider)
        await session.commit()
    
    return LlmProviderPublic(
        id=provider.id,
        slug=provider.slug,
        display_name=provider.display_name,
        description=provider.description,
        icon_url=provider.icon_url,
        provider=provider.provider,
        model_name=provider.model_name,
        api_base_url=provider.api_base_url,
        api_key_present=bool(provider.api_key_encrypted),
        timeout=provider.timeout,
        max_chat_tokens=provider.max_chat_tokens,
        thinking_token_budget=provider.thinking_token_budget,
        enabled=provider.enabled,
        is_default=provider.is_default,
        metadata=json.loads(provider.metadata_json or "{}"),
    )

@router.put("/{slug}", response_model=LlmProviderPublic)
async def update_llm_provider(slug: str, body: LlmProviderUpdate):
    """Aggiorna un provider LLM."""
    async with get_async_session_maker()() as session:
        row = (await session.execute(
            select(LlmProvider).where(
                LlmProvider.tenant_id == "default",
                LlmProvider.slug == slug,
            )
        )).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="LLM provider not found")
        
        # Se is_default=True, deseleziona gli altri
        if body.is_default is True:
            await session.execute(
                update(LlmProvider)
                .where(LlmProvider.tenant_id == "default", LlmProvider.slug != slug)
                .values(is_default=False)
            )
        
        # Aggiornamenti
        if body.display_name is not None:
            row.display_name = body.display_name
        if body.description is not None:
            row.description = body.description
        if body.icon_url is not None:
            row.icon_url = body.icon_url
        if body.provider is not None:
            row.provider = body.provider
        if body.model_name is not None:
            row.model_name = body.model_name
        if body.api_base_url is not None:
            row.api_base_url = body.api_base_url
        if body.api_key is not None:
            # Cripta la nuova API key
            row.api_key_encrypted = encrypt_value(body.api_key)
        if body.timeout is not None:
            row.timeout = body.timeout
        if body.max_chat_tokens is not None:
            row.max_chat_tokens = body.max_chat_tokens
        if body.thinking_token_budget is not None:
            row.thinking_token_budget = body.thinking_token_budget
        if body.enabled is not None:
            row.enabled = body.enabled
        if body.is_default is not None:
            row.is_default = body.is_default
        if body.metadata is not None:
            row.metadata_json = json.dumps(body.metadata)
        
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
    
    return LlmProviderPublic(
        id=row.id,
        slug=row.slug,
        display_name=row.display_name,
        description=row.description,
        icon_url=row.icon_url,
        provider=row.provider,
        model_name=row.model_name,
        api_base_url=row.api_base_url,
        api_key_present=bool(row.api_key_encrypted),
        timeout=row.timeout,
        max_chat_tokens=row.max_chat_tokens,
        thinking_token_budget=row.thinking_token_budget,
        enabled=row.enabled,
        is_default=row.is_default,
        metadata=json.loads(row.metadata_json or "{}"),
    )

@router.delete("/{slug}")
async def delete_llm_provider(slug: str):
    """Elimina un provider LLM."""
    async with get_async_session_maker()() as session:
        row = (await session.execute(
            select(LlmProvider).where(
                LlmProvider.tenant_id == "default",
                LlmProvider.slug == slug,
            )
        )).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="LLM provider not found")
        
        # Se è il default, lanciare errore
        if row.is_default:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the default LLM provider"
            )
        
        await session.execute(delete(LlmProvider).where(LlmProvider.id == row.id))
        await session.commit()
    return {"ok": True}
