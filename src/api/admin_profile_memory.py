# src/api/admin_profile_memory.py
"""CRUD preferenze utente (USER.md) per profilo."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ..agent_profile import profile_manager
from ..identity import sanitize_user_id
from ..memory.memory_files import ProfileMemoryBundle

router = APIRouter(prefix="/profile-memory", tags=["admin-profile-memory"])


def _optional_memory_auth(
    authorization: Optional[str] = Header(None),
) -> None:
    token = os.getenv("AION_ADMIN_MEMORY_TOKEN", "").strip()
    if not token:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Bearer token richiesto per questa risorsa"
        )
    got = authorization[7:].strip()
    if got != token:
        raise HTTPException(status_code=403, detail="Token non valido")


def _require_profile(slug: str):
    p = profile_manager.get_profile(slug)
    if not p:
        raise HTTPException(status_code=404, detail="Profilo non trovato")
    return p


def _list_user_ids_for_profile(profile_slug: str) -> List[str]:
    root = Path(os.getenv("AION_PROFILE_STATE_DIR", "data/profiles")) / profile_slug
    if not root.is_dir():
        return []
    out: List[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "USER.md").is_file():
            out.append(child.name)
    return out


class UserBody(BaseModel):
    content: str = Field(default="")


@router.get("/{profile_slug}/meta")
async def memory_meta(
    profile_slug: str,
    _auth: None = Depends(_optional_memory_auth),
) -> Dict[str, Any]:
    _require_profile(profile_slug)
    users = _list_user_ids_for_profile(profile_slug)
    return {
        "profile_slug": profile_slug,
        "user_max_chars": int(os.getenv("AION_USER_FILE_MAX_CHARS", "1400")),
        "users": users,
    }


def _enforce_user_or_admin_auth(
    user_id: str,
    authorization: Optional[str] = None,
) -> None:
    # 1. Se è configurato un token admin ed è corretto, autorizza l'accesso come admin
    admin_token = os.getenv("AION_ADMIN_MEMORY_TOKEN", "").strip()
    if admin_token and authorization and authorization.startswith("Bearer "):
        got = authorization[7:].strip()
        if got == admin_token:
            return

    # 2. Altrimenti verifica il token utente della sessione chat
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token di autorizzazione richiesto")

    token = authorization[7:].strip()
    from .auth_login import verify_chat_token

    parsed = verify_chat_token(token)
    if not parsed:
        raise HTTPException(status_code=401, detail="Sessione non valida o scaduta")

    authorized_user_id = sanitize_user_id(parsed["identifier"])
    target_user_id = sanitize_user_id(user_id)
    if authorized_user_id != target_user_id:
        raise HTTPException(
            status_code=403,
            detail="Non sei autorizzato ad accedere o modificare le preferenze di un altro utente",
        )


@router.get("/{profile_slug}/users/{user_id}")
async def get_user_md(
    profile_slug: str,
    user_id: str,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    _require_profile(profile_slug)
    _enforce_user_or_admin_auth(user_id, authorization)
    uid = sanitize_user_id(user_id)
    b = ProfileMemoryBundle(profile_slug, uid)
    return {
        "user_id": uid,
        "content": b.user.read(),
        "path": str(b.user.path),
        "max_chars": b.user.max_chars,
    }


@router.put("/{profile_slug}/users/{user_id}")
async def put_user_md(
    profile_slug: str,
    user_id: str,
    body: UserBody,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    _require_profile(profile_slug)
    _enforce_user_or_admin_auth(user_id, authorization)
    uid = sanitize_user_id(user_id)
    b = ProfileMemoryBundle(profile_slug, uid)
    res = b.user.replace(body.content)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "write failed"))
    return res
