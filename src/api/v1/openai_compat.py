"""OpenAI-compatible facade over the AION agent.

External apps that speak ``/v1/models`` and ``/v1/chat/completions`` can treat
each AION profile as a model. The profile's tools and system prompt stay in
effect; a ``tools`` array on the request is ignored.

Conversation continuity uses short-term memory on a stable session id:

- ``X-AION-Conversation-Id`` (or ``metadata.aion_conversation_id``) when the
  client can send it
- otherwise a session derived from the caller, the model, and the first user
  message, so a client that resends the full transcript stays on one session

Later turns send only the newest user message. The first turn also includes
client system text and any earlier transcript, because the session is empty.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.api.v1.chat import _resolve_chat_user_id
from src.session_workspace import normalize_session_id

logger = logging.getLogger("aion.v1.openai_compat")

router = APIRouter(tags=["openai-compatible"])

_MODEL_PERMISSION = {
    "id": "modelperm-aion",
    "object": "model_permission",
    "created": 0,
    "allow_create_engine": False,
    "allow_sampling": True,
    "allow_logprobs": False,
    "allow_search_indices": False,
    "allow_view": True,
    "allow_fine_tuning": False,
    "organization": "*",
    "group": None,
    "is_blocking": False,
}


class OpenAIMessage(BaseModel):
    role: str
    content: Any = None
    model_config = ConfigDict(extra="ignore")


class ChatCompletionBody(BaseModel):
    model: str
    messages: List[OpenAIMessage] = Field(default_factory=list)
    stream: bool = False
    user: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    n: Optional[int] = None
    tools: Optional[Any] = None
    stream_options: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(extra="ignore")


@dataclass
class ParsedMessages:
    systems: List[str]
    transcript: List[tuple[str, str]]
    last_user: str
    first_user: str


def split_model(model: str) -> tuple[str, Optional[str]]:
    """``profile`` or ``profile@llm_provider_slug``."""
    raw = (model or "").strip()
    if "@" not in raw:
        return raw, None
    slug, provider = raw.split("@", 1)
    provider = provider.strip() or None
    return slug.strip(), provider


def message_text(content: Any) -> str:
    """Flatten OpenAI string or content-part content to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        return "\n".join(parts)
    return str(content)


def parse_messages(messages: List[OpenAIMessage]) -> Optional[ParsedMessages]:
    """Return None when the transcript has no user text."""
    systems: List[str] = []
    transcript: List[tuple[str, str]] = []
    for message in messages:
        text = message_text(message.content).strip()
        if not text:
            continue
        role = (message.role or "").strip().lower()
        if role in ("system", "developer"):
            systems.append(text)
        elif role in ("user", "assistant"):
            transcript.append((role, text))
    user_indexes = [i for i, (role, _) in enumerate(transcript) if role == "user"]
    if not user_indexes:
        return None
    last_i = user_indexes[-1]
    # Drop a trailing assistant prefill; the turn ends at the last user message.
    transcript = transcript[: last_i + 1]
    first_user = next(text for role, text in transcript if role == "user")
    return ParsedMessages(
        systems=systems,
        transcript=transcript,
        last_user=transcript[-1][1],
        first_user=first_user,
    )


def build_user_input(parsed: ParsedMessages, *, session_has_history: bool) -> str:
    """Prompt for this turn.

    A session that already has short-term memory only needs the new user
    message. The first turn carries client instructions and prior transcript
    because nothing is stored yet.
    """
    if session_has_history:
        return parsed.last_user
    parts: List[str] = []
    if parsed.systems:
        parts.append(
            "Instructions from the calling application:\n" + "\n\n".join(parsed.systems)
        )
    if len(parsed.transcript) > 1:
        lines = ["Earlier messages:"]
        for role, text in parsed.transcript[:-1]:
            label = "User" if role == "user" else "Assistant"
            lines.append(f"{label}: {text}")
        lines.append("")
        lines.append(parsed.transcript[-1][1])
        parts.append("\n".join(lines))
    else:
        parts.append(parsed.last_user)
    return "\n\n".join(parts)


def derived_conversation_id(user_id: str, model: str, first_user_text: str) -> str:
    digest = hashlib.sha256(
        f"{user_id}\n{model}\n{first_user_text}".encode("utf-8")
    ).hexdigest()[:32]
    return f"oai-{digest}"


def resolve_conversation_id(
    *,
    header: Optional[str],
    metadata: Optional[Dict[str, Any]],
    user_id: str,
    model: str,
    first_user_text: str,
) -> str:
    explicit = (header or "").strip()
    if not explicit and isinstance(metadata, dict):
        explicit = str(
            metadata.get("aion_conversation_id")
            or metadata.get("conversation_id")
            or ""
        ).strip()
    if explicit:
        return normalize_session_id(explicit)
    return derived_conversation_id(user_id, model, first_user_text)


def approx_usage(prompt: str, completion: str) -> Dict[str, int]:
    prompt_tokens = len(prompt) // 4
    completion_tokens = len(completion) // 4
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def completion_payload(
    *,
    completion_id: str,
    created: int,
    model: str,
    text: str,
    prompt: str,
    conversation_id: str,
) -> Dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": approx_usage(prompt, text),
        "aion_conversation_id": conversation_id,
    }


def iter_stream_deltas(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map agent stream events to OpenAI ``delta`` objects.

    ``token`` events are deltas. A following ``final`` event is the full
    answer and is emitted only for the suffix that was not streamed yet.
    """
    sent = ""
    role_sent = False
    deltas: List[Dict[str, Any]] = []

    def emit(delta: Dict[str, Any]) -> None:
        nonlocal role_sent
        if not role_sent:
            delta = {"role": "assistant", **delta}
            role_sent = True
        deltas.append(delta)

    for event in events:
        kind = event.get("type")
        if kind == "token":
            piece = str(event.get("content") or "")
            if not piece:
                continue
            sent += piece
            emit({"content": piece})
        elif kind == "reasoning":
            piece = str(event.get("reasoning") or "")
            if piece:
                emit({"reasoning_content": piece})
        elif kind == "final":
            text = str(event.get("text") or "")
            if text.startswith(sent):
                rest = text[len(sent) :]
                if rest:
                    emit({"content": rest})
            elif not sent and text:
                emit({"content": text})
        elif kind == "error" and not sent:
            emit({"content": str(event.get("content") or "Agent error")})
    return deltas


def model_card(
    profile: Dict[str, Any], *, model_id: Optional[str] = None
) -> Dict[str, Any]:
    slug = str(profile.get("slug") or "")
    public_id = model_id or slug
    return {
        "id": public_id,
        "object": "model",
        "created": 0,
        "owned_by": "aion",
        "root": slug,
        "parent": None,
        "permission": [_MODEL_PERMISSION],
        "name": profile.get("name") or slug,
        "description": profile.get("description") or "",
    }


def _error(
    status: int,
    message: str,
    err_type: str,
    *,
    param: Optional[str] = None,
    code: Optional[str] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": message,
                "type": err_type,
                "param": param,
                "code": code,
            }
        },
    )


def _timeout_seconds() -> float:
    raw = (os.getenv("AION_OPENAI_COMPAT_TIMEOUT_SEC") or "300").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 300.0


def _wants_usage(body: ChatCompletionBody) -> bool:
    options = body.stream_options or {}
    return bool(options.get("include_usage"))


async def _profiles_for(user_row_id: Optional[str]) -> List[Dict[str, Any]]:
    from src.api.main import get_allowed_profiles_for_user

    return await get_allowed_profiles_for_user(user_row_id)


async def _session_has_history(session_id: str, profile_slug: str) -> bool:
    try:
        from src.api.history import history_manager

        window = await history_manager.get_window(
            session_id,
            profile_slug,
            max_turns=1,
            char_limit=200,
        )
        return bool(window)
    except Exception as exc:
        logger.warning("openai compat history check failed: %s", exc)
        return False


async def _ensure_conversation(
    conversation_id: str,
    *,
    user_id: str,
    profile_slug: str,
    llm_provider_name: Optional[str],
) -> None:
    if os.getenv("AION_UNIFIED_DB", "1").lower() not in ("1", "true", "yes"):
        return
    try:
        from src.data.engine import get_async_session_maker
        from src.data.models import Conversation

        tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
        async with get_async_session_maker()() as session:
            row = await session.get(Conversation, conversation_id)
            if row:
                return
            meta: Dict[str, Any] = {"agent_mode": "normal", "source": "openai_compat"}
            if llm_provider_name:
                meta["llm_provider_name"] = llm_provider_name
            session.add(
                Conversation(
                    id=conversation_id,
                    tenant_id=tenant,
                    user_id=user_id,
                    profile_slug=profile_slug,
                    title=None,
                    message_count=0,
                    metadata_json=json.dumps(meta),
                )
            )
            await session.commit()
    except Exception as exc:
        logger.warning("openai compat conversation ensure failed: %s", exc)


async def _turn_runtime(user_id: str, profile_slug: str) -> Dict[str, Any]:
    from src.api.v1.chat import _clamped_runtime

    return await _clamped_runtime(None, user_id, profile_slug)


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chunk(
    *,
    completion_id: str,
    created: int,
    model: str,
    delta: Dict[str, Any],
    finish_reason: Optional[str] = None,
    usage: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


async def _resolve_profile(
    slug: str,
    auth: ChatAuthIdentity,
):
    from src.agent_profile import profile_manager

    known = profile_manager.get_profile(slug)
    if known is None:
        return None, _error(
            404,
            f"The model '{slug}' does not exist.",
            "invalid_request_error",
            param="model",
            code="model_not_found",
        )
    profiles = await _profiles_for(auth.user_row_id)
    allowed = {str(p.get("slug")) for p in profiles}
    if known.slug not in allowed:
        return None, _error(
            403,
            f"The model '{known.slug}' is not available for this user.",
            "invalid_request_error",
            param="model",
            code="model_not_allowed",
        )
    card = next((p for p in profiles if p.get("slug") == known.slug), None)
    return (
        known,
        card
        or {"slug": known.slug, "name": known.name, "description": known.description},
    ), None


@router.get("/models")
async def list_models(auth: ChatAuthIdentity = Depends(require_chat_auth)):
    profiles = await _profiles_for(auth.user_row_id)
    data = [
        model_card(p)
        for p in sorted(profiles, key=lambda item: str(item.get("slug") or ""))
    ]
    return {"object": "list", "data": data}


@router.get("/models/{model_id}")
async def retrieve_model(
    model_id: str,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    slug, provider = split_model(model_id)
    if not slug:
        return _error(
            400,
            "model is required",
            "invalid_request_error",
            param="model",
            code="model_required",
        )
    resolved, err = await _resolve_profile(slug, auth)
    if err is not None:
        return err
    _known, card = resolved
    public_id = model_id.strip()
    if provider:
        public_id = f"{card['slug']}@{provider}"
    return model_card(card, model_id=public_id)


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_conversation_id: Optional[str] = Header(
        None, alias="X-AION-Conversation-Id"
    ),
    x_aion_llm_provider: Optional[str] = Header(None, alias="X-AION-Llm-Provider"),
):
    if body.n not in (None, 1):
        return _error(
            400,
            "Only n=1 is supported. AION runs one agent turn per request.",
            "invalid_request_error",
            param="n",
            code="n_not_supported",
        )
    if body.tools:
        logger.debug("ignoring client tools; the profile's tools are used")

    slug, model_provider = split_model(body.model)
    if not slug:
        return _error(
            400,
            "model is required",
            "invalid_request_error",
            param="model",
            code="model_required",
        )
    provider = (x_aion_llm_provider or "").strip() or model_provider

    resolved, err = await _resolve_profile(slug, auth)
    if err is not None:
        return err
    known, _card = resolved
    profile_slug = known.slug
    public_model = f"{profile_slug}@{provider}" if provider else profile_slug

    parsed = parse_messages(body.messages)
    if parsed is None:
        return _error(
            400,
            "messages must include a user message with text",
            "invalid_request_error",
            param="messages",
            code="missing_user_message",
        )

    uid = _resolve_chat_user_id(
        auth,
        body_user_id=body.user,
        x_aion_user_id=x_aion_user_id,
    )
    try:
        conversation_id = resolve_conversation_id(
            header=x_aion_conversation_id,
            metadata=body.metadata,
            user_id=uid,
            model=public_model,
            first_user_text=parsed.first_user,
        )
    except ValueError as exc:
        return _error(
            400,
            str(exc),
            "invalid_request_error",
            param="X-AION-Conversation-Id",
            code="invalid_conversation_id",
        )

    has_history = await _session_has_history(conversation_id, profile_slug)
    user_input = build_user_input(parsed, session_has_history=has_history)
    await _ensure_conversation(
        conversation_id,
        user_id=uid,
        profile_slug=profile_slug,
        llm_provider_name=provider,
    )

    from src.agent_pipeline import AgentPipeline
    from src.main import get_agent, set_event_loop

    set_event_loop(asyncio.get_running_loop())
    timeout = _timeout_seconds()
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    headers = {
        "X-AION-Conversation-Id": conversation_id,
        "Cache-Control": "no-cache",
    }

    try:
        agent_instance, profile_name = await get_agent(
            profile_slug,
            session_id=conversation_id,
            user_id=uid,
            agent_mode="normal",
            message_source="user_input",
            llm_provider_name=provider,
        )
        pipeline = AgentPipeline(
            agent=agent_instance,
            session_id=conversation_id,
            profile_name=profile_name,
            user_id=uid,
            agent_mode="normal",
        )
        runtime = await _turn_runtime(uid, profile_name)
    except Exception as exc:
        from src.agent_profile import ProfileNotFoundError

        if isinstance(exc, ProfileNotFoundError):
            return _error(
                404,
                str(exc),
                "invalid_request_error",
                param="model",
                code="model_not_found",
            )
        logger.exception("openai compat agent setup failed")
        return _error(500, str(exc), "api_error", code="agent_setup_failed")

    if not body.stream:
        try:
            async with asyncio.timeout(timeout):
                result = await pipeline.run(
                    user_input,
                    message_source="user_input",
                    reasoning_effort="off",
                    metadata={"source": "openai_compat"},
                    runtime=runtime,
                )
        except TimeoutError:
            return _error(
                504,
                f"Agent turn timed out after {timeout:.0f}s",
                "timeout",
                code="timeout",
            )
        except Exception as exc:
            logger.exception(
                "openai compat completion failed conv=%s", conversation_id[:12]
            )
            return _error(500, str(exc), "api_error", code="agent_failed")

        text = result.get("text") or ""
        if not text and result.get("error"):
            text = str(result["error"])
        payload = completion_payload(
            completion_id=completion_id,
            created=created,
            model=public_model,
            text=text,
            prompt=user_input,
            conversation_id=conversation_id,
        )
        return JSONResponse(status_code=200, content=payload, headers=headers)

    include_usage = _wants_usage(body)

    async def generate():
        sent = ""
        role_sent = False
        final_text = ""

        def emit(delta: Dict[str, Any]) -> str:
            nonlocal role_sent
            if not role_sent:
                delta = {"role": "assistant", **delta}
                role_sent = True
            return _sse(
                _chunk(
                    completion_id=completion_id,
                    created=created,
                    model=public_model,
                    delta=delta,
                )
            )

        try:
            async with asyncio.timeout(timeout):
                async for event in pipeline.run_stream(
                    user_input,
                    message_source="user_input",
                    reasoning_effort="off",
                    metadata={"source": "openai_compat"},
                    runtime=runtime,
                ):
                    kind = event.get("type")
                    if kind == "token":
                        piece = str(event.get("content") or "")
                        if not piece:
                            continue
                        sent += piece
                        final_text = sent
                        yield emit({"content": piece})
                    elif kind == "reasoning":
                        piece = str(event.get("reasoning") or "")
                        if piece:
                            yield emit({"reasoning_content": piece})
                    elif kind == "final":
                        text = str(event.get("text") or "")
                        final_text = text or final_text
                        if text.startswith(sent):
                            rest = text[len(sent) :]
                            if rest:
                                sent += rest
                                yield emit({"content": rest})
                        elif not sent and text:
                            sent = text
                            yield emit({"content": text})
                    elif kind == "error" and not sent:
                        text = str(event.get("content") or "Agent error")
                        sent = text
                        final_text = text
                        yield emit({"content": text})
                    elif kind == "tool_event":
                        yield ": aion-tool\n\n"
        except TimeoutError:
            if not sent:
                text = f"Agent turn timed out after {timeout:.0f}s"
                sent = text
                final_text = text
                yield emit({"content": text})
        except Exception as exc:
            logger.exception(
                "openai compat stream failed conv=%s", conversation_id[:12]
            )
            if not sent:
                sent = str(exc)
                final_text = sent
                yield emit({"content": sent})

        finish_delta: Dict[str, Any] = {} if role_sent else {"role": "assistant"}
        usage = approx_usage(user_input, final_text or sent) if include_usage else None
        yield _sse(
            _chunk(
                completion_id=completion_id,
                created=created,
                model=public_model,
                delta=finish_delta,
                finish_reason="stop",
                usage=usage,
            )
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={**headers, "X-Accel-Buffering": "no"},
    )
