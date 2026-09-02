"""Apply legacy Word conversion after session upload (blocking, API host)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from src.tools.office_convert import (
    conversion_manifest_path,
    convert_legacy_word_sync,
    is_legacy_word_upload,
    office_auto_convert_enabled,
    retry_legacy_word_conversion,
)

logger = logging.getLogger("aion.office_auto_convert")


def _persist_manifest(session_id: str, upload_meta: dict[str, Any]) -> None:
    rel = str(upload_meta.get("relative_path") or "")
    if not rel:
        return
    path = conversion_manifest_path(session_id, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "relative_path": rel,
        "original_name": upload_meta.get("original_name"),
        "legacy_word": upload_meta.get("legacy_word"),
        "conversion_status": upload_meta.get("conversion_status"),
        "converted_docx_path": upload_meta.get("converted_docx_path"),
        "conversion_error": upload_meta.get("conversion_error"),
        "conversion_note": upload_meta.get("conversion_note"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_conversion_manifest(session_id: str, upload_rel: str) -> dict[str, Any] | None:
    path = conversion_manifest_path(session_id, upload_rel)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    status = str(data.get("conversion_status") or "")
    conv = data.get("converted_docx_path")
    if status != "ok" or not conv:
        retried = retry_legacy_word_conversion(session_id, upload_rel)
        _persist_manifest(session_id, retried)
        if retried.get("conversion_status") == "ok":
            return {
                "relative_path": upload_rel,
                "original_name": retried.get("original_name"),
                "legacy_word": True,
                "conversion_status": "ok",
                "converted_docx_path": retried.get("converted_docx_path"),
                "conversion_note": retried.get("conversion_note"),
            }
        return data
    return data


async def apply_legacy_word_conversion(
    session_id: str,
    upload_meta: dict[str, Any],
) -> dict[str, Any]:
    if not office_auto_convert_enabled():
        return upload_meta
    name = str(upload_meta.get("original_name") or "")
    mime = str(upload_meta.get("mime") or "")
    if not is_legacy_word_upload(name, mime):
        return upload_meta
    try:
        meta = await asyncio.to_thread(
            convert_legacy_word_sync, session_id, dict(upload_meta)
        )
        await asyncio.to_thread(_persist_manifest, session_id, meta)
        return meta
    except Exception as exc:
        logger.exception(
            "legacy_word_conversion failed session=%s path=%s",
            session_id[:8],
            upload_meta.get("relative_path"),
        )
        upload_meta = dict(upload_meta)
        upload_meta.update(
            {
                "legacy_word": True,
                "conversion_status": "failed",
                "conversion_error": str(exc),
            }
        )
        return upload_meta
