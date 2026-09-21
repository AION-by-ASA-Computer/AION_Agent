"""Per-user runtime settings and named presets (chat-ui sidebar)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.identity import sanitize_user_id
from src.runtime.runtime_settings import (
    clamp_runtime_values,
    load_user_runtime_blob,
    new_preset,
    profile_step_cap,
    public_schema_payload,
    save_user_runtime_blob,
)
from src.runtime.runtime_settings_schema import (
    HARD_MAX_AGENT_STEPS,
    MAX_PRESETS_PER_USER,
    PRESET_NAME_MAX_LEN,
    RUNTIME_ALLOWLIST,
)

router = APIRouter(prefix="/runtime-settings", tags=["v1-runtime-settings"])

ReasoningEffort = Literal["min", "medium", "max"]


class RuntimeSettingsPayload(BaseModel):
    """Allowlisted overrides. Unknown keys are rejected."""

    max_agent_steps: Optional[int] = None
    max_tool_calls: Optional[int] = None
    max_tool_events: Optional[int] = None
    turn_timeout_sec: Optional[float] = None
    no_progress_timeout_sec: Optional[float] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    repetition_penalty: Optional[float] = None
    seed: Optional[int] = None
    thinking_enabled: Optional[bool] = None
    reasoning_effort: Optional[ReasoningEffort] = None
    thinking_token_budget: Optional[int] = None
    reasoning_max_chars: Optional[int] = None
    reasoning_max_events: Optional[int] = None
    reasoning_min_chars: Optional[int] = None
    reasoning_min_events: Optional[int] = None
    reasoning_max_level_chars: Optional[int] = None
    reasoning_max_level_events: Optional[int] = None
    reasoning_hard_stop: Optional[bool] = None

    class Config:
        extra = "ignore"


class PutRuntimeSettingsBody(BaseModel):
    values: RuntimeSettingsPayload = Field(default_factory=RuntimeSettingsPayload)
    active_preset_id: Optional[str] = None


class CreatePresetBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=PRESET_NAME_MAX_LEN)
    values: Optional[RuntimeSettingsPayload] = None


class PatchPresetBody(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=PRESET_NAME_MAX_LEN)
    values: Optional[RuntimeSettingsPayload] = None


def _uid(auth: ChatAuthIdentity, x_user: Optional[str]) -> str:
    if auth.via == "chat_token" and auth.identifier:
        return sanitize_user_id(auth.identifier)
    return sanitize_user_id(x_user or auth.identifier)


def _payload_dict(payload: Optional[RuntimeSettingsPayload]) -> Dict[str, Any]:
    if payload is None:
        return {}
    raw = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    return {k: v for k, v in raw.items() if v is not None}


def _user_public(blob: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    values = dict(defaults)
    values.update(blob.get("values") or {})
    return {
        "values": values,
        "stored_values": blob.get("values") or {},
        "presets": blob.get("presets") or [],
        "active_preset_id": blob.get("active_preset_id"),
    }


@router.get("")
async def get_runtime_settings(
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    profile: Optional[str] = Query(None),
) -> Dict[str, Any]:
    schema_payload = public_schema_payload()
    uid = _uid(auth, x_aion_user_id)
    blob = await load_user_runtime_blob(uid)
    return {
        **schema_payload,
        "user": _user_public(blob, schema_payload["defaults"]),
        "allowlist": sorted(RUNTIME_ALLOWLIST),
        "limits": {
            "hard_max_agent_steps": HARD_MAX_AGENT_STEPS,
            "profile_max_agent_steps": profile_step_cap(profile),
        },
    }


@router.put("")
async def put_runtime_settings(
    body: PutRuntimeSettingsBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> Dict[str, Any]:
    uid = _uid(auth, x_aion_user_id)
    blob = await load_user_runtime_blob(uid)
    blob["values"] = clamp_runtime_values(_payload_dict(body.values))
    if body.active_preset_id is not None:
        blob["active_preset_id"] = body.active_preset_id or None
    try:
        saved = await save_user_runtime_blob(uid, blob)
    except LookupError:
        saved = blob
    schema_payload = public_schema_payload()
    return {"ok": True, "user": _user_public(saved, schema_payload["defaults"])}


@router.post("/presets")
async def create_preset(
    body: CreatePresetBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> Dict[str, Any]:
    uid = _uid(auth, x_aion_user_id)
    blob = await load_user_runtime_blob(uid)
    presets: List[Dict[str, Any]] = list(blob.get("presets") or [])
    if len(presets) >= MAX_PRESETS_PER_USER:
        raise HTTPException(400, detail=f"Maximum {MAX_PRESETS_PER_USER} presets")
    source = _payload_dict(body.values) if body.values is not None else blob.get("values")
    try:
        preset = new_preset(body.name, source or {})
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    presets.append(preset)
    blob["presets"] = presets
    blob["active_preset_id"] = preset["id"]
    blob["values"] = preset["values"]
    try:
        saved = await save_user_runtime_blob(uid, blob)
    except LookupError:
        saved = blob
    schema_payload = public_schema_payload()
    return {"ok": True, "preset": preset, "user": _user_public(saved, schema_payload["defaults"])}


@router.patch("/presets/{preset_id}")
async def patch_preset(
    preset_id: str,
    body: PatchPresetBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> Dict[str, Any]:
    uid = _uid(auth, x_aion_user_id)
    blob = await load_user_runtime_blob(uid)
    presets = list(blob.get("presets") or [])
    found = None
    for item in presets:
        if item.get("id") == preset_id:
            found = item
            break
    if found is None:
        raise HTTPException(404, detail="preset_not_found")
    if body.name is not None:
        found["name"] = body.name.strip()[:PRESET_NAME_MAX_LEN]
    if body.values is not None:
        found["values"] = clamp_runtime_values(_payload_dict(body.values))
        if blob.get("active_preset_id") == preset_id:
            blob["values"] = found["values"]
    found["updated_at"] = datetime.now(timezone.utc).isoformat()
    blob["presets"] = presets
    try:
        saved = await save_user_runtime_blob(uid, blob)
    except LookupError:
        saved = blob
    schema_payload = public_schema_payload()
    return {"ok": True, "preset": found, "user": _user_public(saved, schema_payload["defaults"])}


@router.delete("/presets/{preset_id}")
async def delete_preset(
    preset_id: str,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> Dict[str, Any]:
    uid = _uid(auth, x_aion_user_id)
    blob = await load_user_runtime_blob(uid)
    presets = [p for p in (blob.get("presets") or []) if p.get("id") != preset_id]
    if len(presets) == len(blob.get("presets") or []):
        raise HTTPException(404, detail="preset_not_found")
    blob["presets"] = presets
    if blob.get("active_preset_id") == preset_id:
        blob["active_preset_id"] = None
    try:
        saved = await save_user_runtime_blob(uid, blob)
    except LookupError:
        saved = blob
    schema_payload = public_schema_payload()
    return {"ok": True, "user": _user_public(saved, schema_payload["defaults"])}


@router.post("/presets/{preset_id}/activate")
async def activate_preset(
    preset_id: str,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> Dict[str, Any]:
    uid = _uid(auth, x_aion_user_id)
    blob = await load_user_runtime_blob(uid)
    found = next((p for p in (blob.get("presets") or []) if p.get("id") == preset_id), None)
    if found is None:
        raise HTTPException(404, detail="preset_not_found")
    blob["active_preset_id"] = preset_id
    blob["values"] = clamp_runtime_values(found.get("values") or {})
    try:
        saved = await save_user_runtime_blob(uid, blob)
    except LookupError:
        saved = blob
    schema_payload = public_schema_payload()
    return {"ok": True, "user": _user_public(saved, schema_payload["defaults"])}


