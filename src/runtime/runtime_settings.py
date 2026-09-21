"""Clamp, persist, and resolve per-user runtime settings for a chat turn."""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from src.runtime.runtime_settings_schema import (
    MAX_PRESETS_PER_USER,
    OPENAI_SAMPLING_KEYS,
    PRESET_NAME_MAX_LEN,
    RUNTIME_FIELD_BY_KEY,
    RUNTIME_FIELDS,
    RUNTIME_SETTINGS_META_KEY,
    TURN_BUDGET_KEY_MAP,
    VLLM_EXTRA_SAMPLING_KEYS,
    RuntimeFieldSpec,
    schema_public,
)

logger = logging.getLogger("aion.runtime_settings")


def _parse_bool(raw: Any, fallback: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return fallback
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return fallback


def _clamp_number(value: float, spec: RuntimeFieldSpec) -> float:
    n = value
    if spec.min_value is not None:
        n = max(spec.min_value, n)
    if spec.max_value is not None:
        n = min(spec.max_value, n)
    return n


def _parse_field(spec: RuntimeFieldSpec, raw: Any) -> Any:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        if spec.nullable:
            return None
        return spec.fallback
    if spec.kind == "bool":
        return _parse_bool(raw, bool(spec.fallback))
    if spec.kind == "enum":
        text = str(raw).strip().lower()
        allowed = spec.enum_values or ()
        if text in allowed:
            return text
        return spec.fallback
    if spec.kind == "int":
        try:
            n = int(float(raw))
        except (TypeError, ValueError):
            return spec.fallback if not spec.nullable else None
        return int(_clamp_number(n, spec))
    if spec.kind == "float":
        try:
            n = float(raw)
        except (TypeError, ValueError):
            return spec.fallback if not spec.nullable else None
        return float(_clamp_number(n, spec))
    return spec.fallback


def _env_raw(spec: RuntimeFieldSpec) -> Any:
    raw = os.getenv(spec.env_key)
    if raw is None or not str(raw).strip():
        if spec.key == "max_agent_steps":
            try:
                from src.settings import get_settings

                return int(get_settings().max_agent_steps)
            except Exception:
                return spec.fallback
        if spec.key == "max_tool_calls":
            try:
                from src.settings import get_settings

                return int(get_settings().tool_calls_max_per_turn)
            except Exception:
                return spec.fallback
        if spec.key == "no_progress_timeout_sec":
            try:
                from src.settings import get_settings

                return float(get_settings().no_progress_timeout_sec)
            except Exception:
                return spec.fallback
        if spec.key == "max_tokens":
            try:
                from src.settings import get_settings

                return int(get_settings().chat_max_tokens)
            except Exception:
                return spec.fallback
        if spec.key == "reasoning_effort":
            try:
                from src.runtime.reasoning_effort import effective_reasoning_effort

                return effective_reasoning_effort(None)
            except Exception:
                return spec.fallback
        return spec.fallback
    return raw


def defaults_from_env() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for spec in RUNTIME_FIELDS:
        out[spec.key] = _parse_field(spec, _env_raw(spec))
    return out


def clamp_runtime_values(incoming: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep allowlisted keys only and clamp each value."""
    src = incoming if isinstance(incoming, dict) else {}
    out: Dict[str, Any] = {}
    for key, raw in src.items():
        spec = RUNTIME_FIELD_BY_KEY.get(str(key))
        if spec is None:
            continue
        out[spec.key] = _parse_field(spec, raw)
    return out


def merge_runtime_layers(
    *layers: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Later layers override earlier ones. Always starts from env defaults."""
    merged = defaults_from_env()
    for layer in layers:
        if not layer:
            continue
        merged.update(clamp_runtime_values(layer))
    return clamp_runtime_values(merged)


def apply_profile_and_provider_caps(
    values: Dict[str, Any],
    *,
    profile_max_agent_steps: Optional[int] = None,
    provider_max_chat_tokens: Optional[int] = None,
    context_window: Optional[int] = None,
) -> Dict[str, Any]:
    out = dict(values)
    steps = out.get("max_agent_steps")
    if steps is not None and profile_max_agent_steps:
        try:
            cap = int(profile_max_agent_steps)
            if cap > 0:
                out["max_agent_steps"] = min(int(steps), cap)
        except (TypeError, ValueError):
            pass
    tokens = out.get("max_tokens")
    caps: List[int] = []
    if provider_max_chat_tokens:
        try:
            caps.append(int(provider_max_chat_tokens))
        except (TypeError, ValueError):
            pass
    if context_window:
        try:
            caps.append(max(256, int(context_window) // 2))
        except (TypeError, ValueError):
            pass
    if tokens is not None and caps:
        out["max_tokens"] = min(int(tokens), *caps)
    return clamp_runtime_values(out)


def empty_user_blob() -> Dict[str, Any]:
    return {"active_preset_id": None, "values": {}, "presets": []}


def sanitize_user_blob(raw: Any) -> Dict[str, Any]:
    blob = empty_user_blob()
    if not isinstance(raw, dict):
        return blob
    blob["values"] = clamp_runtime_values(raw.get("values") or {})
    aid = raw.get("active_preset_id")
    blob["active_preset_id"] = str(aid) if aid else None
    presets_in = raw.get("presets") or []
    presets: List[Dict[str, Any]] = []
    if isinstance(presets_in, list):
        for item in presets_in[:MAX_PRESETS_PER_USER]:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id") or "").strip() or uuid.uuid4().hex
            name = str(item.get("name") or "").strip()[:PRESET_NAME_MAX_LEN]
            if not name:
                continue
            presets.append(
                {
                    "id": pid,
                    "name": name,
                    "values": clamp_runtime_values(item.get("values") or {}),
                    "created_at": str(item.get("created_at") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                }
            )
    blob["presets"] = presets
    if blob["active_preset_id"] and not any(
        p["id"] == blob["active_preset_id"] for p in presets
    ):
        blob["active_preset_id"] = None
    return blob


async def load_user_runtime_blob(user_id: Optional[str]) -> Dict[str, Any]:
    if not user_id:
        return empty_user_blob()
    try:
        from sqlalchemy import select

        from src.data.engine import get_async_session_maker
        from src.data.models import User

        async with get_async_session_maker()() as session:
            rows = (
                (await session.execute(select(User).where(User.identifier == user_id)))
                .scalars()
                .all()
            )
            user = rows[0] if rows else None
            if not user or not user.metadata_json:
                return empty_user_blob()
            meta = json.loads(user.metadata_json)
            return sanitize_user_blob(meta.get(RUNTIME_SETTINGS_META_KEY))
    except Exception as exc:
        logger.warning("load runtime settings failed user=%s: %s", user_id, exc)
        return empty_user_blob()


async def save_user_runtime_blob(user_id: str, blob: Dict[str, Any]) -> Dict[str, Any]:
    clean = sanitize_user_blob(blob)
    from sqlalchemy import select

    from src.data.engine import get_async_session_maker
    from src.data.models import User

    async with get_async_session_maker()() as session:
        rows = (
            (await session.execute(select(User).where(User.identifier == user_id)))
            .scalars()
            .all()
        )
        user = rows[0] if rows else None
        if user is None:
            raise LookupError("user_not_found")
        meta: Dict[str, Any] = {}
        if user.metadata_json:
            try:
                meta = json.loads(user.metadata_json) or {}
            except Exception:
                meta = {}
        meta[RUNTIME_SETTINGS_META_KEY] = clean
        user.metadata_json = json.dumps(meta, ensure_ascii=False)
        session.add(user)
        await session.commit()
    return clean


def profile_step_cap(profile_name: Optional[str]) -> Optional[int]:
    if not profile_name:
        return None
    try:
        from src.agent_profile import profile_manager

        profile = profile_manager.get_profile(profile_name)
        cap = getattr(profile, "max_agent_steps", None) if profile else None
        if cap is None:
            return None
        n = int(cap)
        return n if n > 0 else None
    except Exception:
        return None


async def resolve_turn_runtime_settings(
    request_runtime: Optional[Dict[str, Any]],
    user_id: Optional[str],
    *,
    profile_max_agent_steps: Optional[int] = None,
    provider_max_chat_tokens: Optional[int] = None,
    context_window: Optional[int] = None,
) -> Dict[str, Any]:
    user_blob = await load_user_runtime_blob(user_id)
    merged = merge_runtime_layers(user_blob.get("values"), request_runtime)
    return apply_profile_and_provider_caps(
        merged,
        profile_max_agent_steps=profile_max_agent_steps,
        provider_max_chat_tokens=provider_max_chat_tokens,
        context_window=context_window,
    )


def new_preset(name: str, values: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    clean_name = (name or "").strip()[:PRESET_NAME_MAX_LEN]
    if not clean_name:
        raise ValueError("preset_name_required")
    return {
        "id": uuid.uuid4().hex,
        "name": clean_name,
        "values": clamp_runtime_values(values),
        "created_at": now,
        "updated_at": now,
    }


def apply_runtime_to_generation_kwargs(
    gen_kw: Optional[Dict[str, Any]],
    runtime: Optional[Dict[str, Any]],
    *,
    vllm_extra: bool = True,
) -> Dict[str, Any]:
    out = dict(gen_kw or {})
    if not runtime:
        return out
    for key in OPENAI_SAMPLING_KEYS:
        val = runtime.get(key)
        if val is None:
            continue
        out[key] = val
    if runtime.get("thinking_token_budget") is not None:
        eb = dict(out.get("extra_body") or {})
        eb["thinking_token_budget"] = int(runtime["thinking_token_budget"])
        out["extra_body"] = eb
    if vllm_extra:
        extra_bits = {
            k: runtime[k]
            for k in VLLM_EXTRA_SAMPLING_KEYS
            if runtime.get(k) is not None
        }
        if extra_bits:
            eb = dict(out.get("extra_body") or {})
            eb.update(extra_bits)
            out["extra_body"] = eb
    return out


def turn_budget_overrides(
    runtime: Optional[Dict[str, Any]],
    *,
    resolved_effort: Optional[str] = None,
) -> Dict[str, Any]:
    if not runtime:
        return {}
    out: Dict[str, Any] = {}
    for src, dest in TURN_BUDGET_KEY_MAP.items():
        if src in runtime and runtime[src] is not None:
            out[dest] = runtime[src]
    effort = (
        str(resolved_effort or runtime.get("reasoning_effort") or "").strip().lower()
    )
    if effort == "off":
        thinking_on = False
    elif resolved_effort is not None:
        thinking_on = effort not in ("", "off")
    else:
        thinking_on = runtime.get("thinking_enabled")
    if thinking_on is False:
        if runtime.get("reasoning_min_chars") is not None:
            out["max_reasoning_chars"] = runtime["reasoning_min_chars"]
        if runtime.get("reasoning_min_events") is not None:
            out["max_reasoning_events"] = runtime["reasoning_min_events"]
    elif effort == "min":
        if runtime.get("reasoning_min_chars") is not None:
            out["max_reasoning_chars"] = runtime["reasoning_min_chars"]
        if runtime.get("reasoning_min_events") is not None:
            out["max_reasoning_events"] = runtime["reasoning_min_events"]
    elif effort == "max":
        if runtime.get("reasoning_max_level_chars") is not None:
            out["max_reasoning_chars"] = runtime["reasoning_max_level_chars"]
        if runtime.get("reasoning_max_level_events") is not None:
            out["max_reasoning_events"] = runtime["reasoning_max_level_events"]
    return out


def turn_guard_overrides(runtime: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-turn overrides for TurnGuards (not TurnBudget numeric limits)."""
    if not runtime:
        return {}
    out: Dict[str, Any] = {}
    if "reasoning_hard_stop" in runtime and runtime["reasoning_hard_stop"] is not None:
        out["reasoning_hard_stop"] = bool(runtime["reasoning_hard_stop"])
    return out


@contextmanager
def apply_agent_max_steps(agent: Any, steps: Optional[int]) -> Iterator[None]:
    if agent is None or steps is None:
        yield
        return
    prev = getattr(agent, "max_agent_steps", None)
    try:
        agent.max_agent_steps = int(steps)
        yield
    finally:
        if prev is not None:
            agent.max_agent_steps = prev


def public_schema_payload() -> Dict[str, Any]:
    defaults = defaults_from_env()
    schema = schema_public()
    for row in schema:
        row["default"] = defaults.get(row["key"])
    return {"schema": schema, "defaults": defaults}
