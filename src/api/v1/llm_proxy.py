"""Proxy LLM OpenAI-compatibile (senza agente) per client enterprise.

``GET  /v1/llm/models``            elenca i provider LLM abilitati (solo campi non segreti)
``POST /v1/llm/chat/completions``  passthrough verso il provider selezionato da ``model`` (= slug)

Chiavi API, ``api_base_url`` e header del provider restano solo lato server.
Non vengono mai loggati ne' i segreti ne' i corpi dei prompt.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.data.engine import get_async_session_maker
from src.data.models import LlmProvider, User
from src.runtime.credential_store import CredentialDecryptionError, decrypt_value
from src.runtime.llm_probe import resolve_probe_base_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["v1-llm-proxy"])

# Campi inoltrati al provider (contratto enterprise); il resto viene ignorato.
_FORWARD_FIELDS = (
    "messages",
    "tools",
    "tool_choice",
    "temperature",
    "max_tokens",
    "max_completion_tokens",
    "top_p",
    "stop",
    "response_format",
    "reasoning_effort",
    "stream_options",
)

# Provider non OpenAI-compatibili con l'endpoint salvato: 501 provider_not_supported.
_UNSUPPORTED_PROVIDERS = frozenset(
    {"anthropic", "azure", "bedrock", "vertex_ai", "vertex", "cohere", "watsonx"}
)
_GOOGLE_PROVIDERS = frozenset({"google", "gemini"})

_PLACEHOLDER_KEYS = frozenset({"", "none", "placeholder-token"})
_MAX_ERROR_MESSAGE = 500


def _error(
    status: int,
    message: str,
    err_type: str,
    code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": message,
                "type": err_type,
                "param": None,
                "code": code,
            }
        },
        headers=headers,
    )


def _make_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    """Factory del client HTTP upstream (sostituibile nei test)."""
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


async def _resolve_tenant_id(auth: ChatAuthIdentity) -> str:
    default = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    if not auth.user_row_id:
        return default
    try:
        async with get_async_session_maker()() as session:
            tenant = (
                await session.execute(
                    select(User.tenant_id).where(User.id == auth.user_row_id)
                )
            ).scalar_one_or_none()
        return tenant or default
    except Exception:  # noqa: BLE001 - fallback al tenant di default
        logger.warning("llm_proxy: tenant lookup fallito, uso default")
        return default


async def _list_enabled(tenant_id: str):
    async with get_async_session_maker()() as session:
        return (
            (
                await session.execute(
                    select(LlmProvider)
                    .where(
                        LlmProvider.tenant_id == tenant_id,
                        LlmProvider.enabled.is_(True),
                    )
                    .order_by(LlmProvider.is_default.desc(), LlmProvider.display_name)
                )
            )
            .scalars()
            .all()
        )


async def _get_enabled(tenant_id: str, slug: str):
    async with get_async_session_maker()() as session:
        return (
            (
                await session.execute(
                    select(LlmProvider).where(
                        LlmProvider.tenant_id == tenant_id,
                        LlmProvider.slug == slug,
                        LlmProvider.enabled.is_(True),
                    )
                )
            )
            .scalars()
            .first()
        )


@router.get("/models")
async def list_llm_models(auth: ChatAuthIdentity = Depends(require_chat_auth)):
    tenant_id = await _resolve_tenant_id(auth)
    rows = await _list_enabled(tenant_id)
    return {
        "object": "list",
        "data": [
            {
                "id": r.slug,
                "object": "model",
                "owned_by": "aion",
                "name": r.display_name,
                "model_name": r.model_name,
                "description": r.description or "",
                "is_default": bool(r.is_default),
            }
            for r in rows
        ],
    }


def _provider_support_error(row: Any, base_url: str) -> Optional[str]:
    """Messaggio d'errore se il provider non e' raggiungibile via chat/completions OpenAI."""
    p = (row.provider or "openai").strip().lower()
    if p in _UNSUPPORTED_PROVIDERS:
        return (
            f"Provider type '{p}' does not expose an OpenAI-compatible "
            "chat/completions endpoint through this proxy."
        )
    if p in _GOOGLE_PROVIDERS and "/openai" not in base_url:
        return (
            "Google/Gemini providers are supported only with the OpenAI-compatible "
            "endpoint (base URL ending in /openai)."
        )
    if not base_url:
        return "Provider has no usable endpoint configured."
    return None


def _upstream_headers(row: Any) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if row.api_key_encrypted:
        key = decrypt_value(row.api_key_encrypted).strip()
        if key.lower() not in _PLACEHOLDER_KEYS:
            headers["Authorization"] = f"Bearer {key}"
    return headers


def _build_payload(body: Dict[str, Any], row: Any, stream: bool) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        k: body[k] for k in _FORWARD_FIELDS if body.get(k) is not None
    }
    payload["model"] = row.model_name
    payload["stream"] = stream
    if not stream:
        payload.pop("stream_options", None)
    cap = row.max_chat_tokens
    if cap:
        for key in ("max_tokens", "max_completion_tokens"):
            if isinstance(payload.get(key), int):
                payload[key] = min(payload[key], int(cap))
    return payload


def _upstream_error_message(raw: bytes) -> str:
    try:
        data = json.loads(raw)
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:_MAX_ERROR_MESSAGE]
        if isinstance(err, str):
            return err[:_MAX_ERROR_MESSAGE]
        if isinstance(data, dict) and isinstance(data.get("message"), str):
            return data["message"][:_MAX_ERROR_MESSAGE]
    except (ValueError, AttributeError):
        pass
    return "Upstream provider returned an error."


def _translate_upstream_error(status: int, raw: bytes, retry_after: Optional[str]):
    msg = _upstream_error_message(raw)
    if status == 429:
        hdrs = {"Retry-After": retry_after} if retry_after else None
        return _error(429, msg, "rate_limit_error", "rate_limit_exceeded", hdrs)
    if status in (400, 413, 422):
        return _error(
            400 if status == 422 else status,
            msg,
            "invalid_request_error",
            "upstream_bad_request",
        )
    if status in (401, 403):
        # Credenziali del provider errate: non e' colpa del client.
        return _error(
            502,
            "Upstream provider rejected the server credentials.",
            "api_error",
            "upstream_auth_error",
        )
    if status in (408, 504):
        return _error(504, msg, "api_error", "upstream_timeout")
    return _error(502, msg, "api_error", "upstream_error")


def _timeout_for(row: Any) -> httpx.Timeout:
    read = float(row.timeout or 120)
    return httpx.Timeout(connect=10.0, read=read, write=30.0, pool=10.0)


@router.post("/chat/completions")
async def llm_chat_completions(
    request: Request,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "Invalid JSON body.", "invalid_request_error", "invalid_json")
    if not isinstance(body, dict):
        return _error(
            400, "Body must be a JSON object.", "invalid_request_error", "invalid_json"
        )

    slug = body.get("model")
    if not isinstance(slug, str) or not slug.strip():
        return _error(
            400, "'model' is required.", "invalid_request_error", "missing_model"
        )
    slug = slug.strip()
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        return _error(
            400,
            "'messages' must be a non-empty array.",
            "invalid_request_error",
            "invalid_messages",
        )

    tenant_id = await _resolve_tenant_id(auth)
    row = await _get_enabled(tenant_id, slug)
    if row is None:
        return _error(
            404,
            f"The model '{slug}' does not exist or is not enabled.",
            "invalid_request_error",
            "model_not_found",
        )

    base_url = resolve_probe_base_url(row.provider, row.api_base_url)
    unsupported = _provider_support_error(row, base_url)
    if unsupported:
        return _error(501, unsupported, "api_error", "provider_not_supported")

    try:
        headers = _upstream_headers(row)
    except CredentialDecryptionError:
        logger.error("llm_proxy: chiave non decifrabile per provider %s", row.slug)
        return _error(
            502,
            "Provider credentials are not usable.",
            "api_error",
            "upstream_auth_error",
        )

    stream = bool(body.get("stream"))
    payload = _build_payload(body, row, stream)
    url = base_url.rstrip("/") + "/chat/completions"
    client = _make_client(_timeout_for(row))
    logger.info(
        "llm_proxy: provider=%s stream=%s messages=%d",
        row.slug,
        stream,
        len(body["messages"]),
    )

    try:
        req = client.build_request("POST", url, json=payload, headers=headers)
        resp = await client.send(req, stream=True)
    except httpx.TimeoutException:
        await client.aclose()
        return _error(504, "Upstream provider timed out.", "api_error", "upstream_timeout")
    except httpx.HTTPError:
        await client.aclose()
        return _error(
            502, "Upstream provider is unreachable.", "api_error", "upstream_unreachable"
        )

    if resp.status_code >= 400:
        try:
            raw = await resp.aread()
        finally:
            await resp.aclose()
            await client.aclose()
        return _translate_upstream_error(
            resp.status_code, raw, resp.headers.get("retry-after")
        )

    if not stream:
        try:
            raw = await resp.aread()
        except httpx.HTTPError:
            return _error(
                502, "Upstream read failed.", "api_error", "upstream_error"
            )
        finally:
            await resp.aclose()
            await client.aclose()
        try:
            data = json.loads(raw)
        except ValueError:
            return _error(
                502,
                "Upstream returned a non-JSON response.",
                "api_error",
                "upstream_error",
            )
        if isinstance(data, dict):
            data["model"] = row.slug
        return JSONResponse(status_code=200, content=data)

    async def generate() -> AsyncIterator[str]:
        try:
            async for line in resp.aiter_lines():
                yield line + "\n"
        except httpx.HTTPError:
            err = {
                "error": {
                    "message": "Upstream stream interrupted.",
                    "type": "api_error",
                    "param": None,
                    "code": "upstream_error",
                }
            }
            yield f"data: {json.dumps(err)}\n\ndata: [DONE]\n\n"
        finally:
            # Eseguito anche su disconnessione del client (GeneratorExit/cancel).
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
