"""v1 file upload: stores under session workspace + optional StorageBackend."""
from __future__ import annotations

import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.api.auth import AuthContext, Scope, require_scope
from src.session_workspace import save_upload
from src.storage import get_storage_backend

router = APIRouter()


@router.post("/conversations/{conversation_id}/files")
async def upload_files(
    conversation_id: str,
    ctx: AuthContext = Depends(require_scope(Scope.FILES_WRITE)),
    files: List[UploadFile] = File(...),
):
    if not files:
        raise HTTPException(400, "No files")
    out = []
    tenant = ctx.tenant_id
    backend = get_storage_backend()
    for f in files:
        data = await f.read()
        meta = save_upload(conversation_id, f.filename or "upload", data)
        key = f"{tenant}/conversations/{conversation_id}/uploads/{uuid.uuid4().hex[:12]}_{meta.get('name', 'file')}"
        try:
            backend.put_bytes(key, data, meta.get("mime") or "application/octet-stream")
            meta["storage_key"] = key
        except Exception:
            meta["storage_key"] = None
        out.append(meta)
    return {"attachments": out}


@router.get("/conversations/{conversation_id}/files")
async def list_files(
    conversation_id: str,
    ctx: AuthContext = Depends(require_scope(Scope.FILES_READ)),
):
    from src.session_workspace import list_dir

    try:
        rows = list_dir(conversation_id, subdir="uploads")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except OSError as e:
        raise HTTPException(
            503,
            "Session storage not writable. Fix AION_DATA_DIR (local: `data`, not `/app/data`). "
            + str(e),
        ) from e
    return {"files": rows}
