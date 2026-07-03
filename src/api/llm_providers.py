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


class LlmProviderProbeRequest(BaseModel):
    provider: str = Field(..., description="openai, anthropic, gemini, ollama, vllm, …")
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None


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


@router.post("/probe")
async def probe_llm_provider(body: LlmProviderProbeRequest):
    """Test connectivity and list models (GET /v1/models + LiteLLM catalog fallback)."""
    from src.runtime.llm_probe import probe_llm_connection

    try:
        return await probe_llm_connection(
            provider=body.provider,
            api_base_url=body.api_base_url,
            api_key=body.api_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        logger.exception("LLM probe failed for provider=%s", body.provider)
        raise HTTPException(status_code=502, detail=f"Connection failed: {e}") from e


@router.get("", response_model=List[LlmProviderPublic])
async def list_llm_providers(tenant_id: str = "default"):
    """Lista tutti i provider LLM per tenant."""
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(LlmProvider)
                    .where(LlmProvider.tenant_id == tenant_id)
                    .order_by(LlmProvider.is_default.desc(), LlmProvider.display_name)
                )
            )
            .scalars()
            .all()
        )
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
        row = (
            (
                await session.execute(
                    select(LlmProvider).where(
                        LlmProvider.tenant_id == tenant_id,
                        LlmProvider.slug == slug,
                    )
                )
            )
            .scalars()
            .first()
        )
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
                status_code=400, detail="API key required for third-party providers"
            )

    async with get_async_session_maker()() as session:
        # Controlla duplicato
        existing = (
            (
                await session.execute(
                    select(LlmProvider).where(
                        LlmProvider.tenant_id == "default",
                        LlmProvider.slug == body.slug,
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409, detail="Provider with this slug already exists"
            )

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
        row = (
            (
                await session.execute(
                    select(LlmProvider).where(
                        LlmProvider.tenant_id == "default",
                        LlmProvider.slug == slug,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="LLM provider not found")

        # Se is_default=True, deseleziona gli altri
        if body.is_default is True:
            await session.execute(
                update(LlmProvider)
                .where(LlmProvider.tenant_id == "default", LlmProvider.slug != slug)
                .values(is_default=False)
            )

        # Aggiornamenti basati sui campi esplicitamente inviati
        update_data = body.model_dump(exclude_unset=True)

        if "display_name" in update_data:
            row.display_name = update_data["display_name"]
        if "description" in update_data:
            row.description = update_data["description"]
        if "icon_url" in update_data:
            row.icon_url = update_data["icon_url"]
        if "provider" in update_data:
            row.provider = update_data["provider"]
        if "model_name" in update_data:
            row.model_name = update_data["model_name"]
        if "api_base_url" in update_data:
            row.api_base_url = update_data["api_base_url"]
        if "api_key" in update_data:
            if update_data["api_key"] is not None:
                row.api_key_encrypted = encrypt_value(update_data["api_key"])
        if "timeout" in update_data:
            row.timeout = update_data["timeout"]
        if "max_chat_tokens" in update_data:
            row.max_chat_tokens = update_data["max_chat_tokens"]
        if "thinking_token_budget" in update_data:
            row.thinking_token_budget = update_data["thinking_token_budget"]
        if "enabled" in update_data:
            row.enabled = update_data["enabled"]
        if "is_default" in update_data:
            row.is_default = update_data["is_default"]
        if "metadata" in update_data:
            row.metadata_json = json.dumps(update_data["metadata"])

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
        row = (
            (
                await session.execute(
                    select(LlmProvider).where(
                        LlmProvider.tenant_id == "default",
                        LlmProvider.slug == slug,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="LLM provider not found")

        # Se è il default, lanciare errore
        if row.is_default:
            raise HTTPException(
                status_code=400, detail="Cannot delete the default LLM provider"
            )

        await session.execute(delete(LlmProvider).where(LlmProvider.id == row.id))
        await session.commit()
    return {"ok": True}
