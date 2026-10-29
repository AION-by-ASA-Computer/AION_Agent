"""Media handling for the WhatsApp channel (Cloud API).

Inbound: downloads images/documents sent by the user from Meta and stores them
in the conversation sandbox (``uploads/``) with the same post-processing as the
chat-ui upload endpoint (``src/api/v1/files.py``), returning an
``AttachmentRef``-shaped dict for ``AgentPipeline.run_stream``.

Outbound: snapshots the session output folders around an agent turn, detects
the deliverables the agent created and sends them back as WhatsApp
image/document messages (upload to ``/{phone_number_id}/media`` + send by id).

Used by ``dispatcher._handle_linked`` / ``dispatcher.run_turn``.
See ``docs/integrations/whatsapp.md`` (File e foto).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.session_workspace import (
    is_user_facing_generated_file,
    save_upload,
    session_root,
)
from src.storage import get_storage_backend
from src.tools.doc_auto_ingest import schedule_auto_ingest
from src.tools.office_auto_convert import apply_legacy_word_conversion

from .graph_client import GraphClient, GraphError, MediaTooLarge, is_allowed_media_url
from .payload import InboundMedia

logger = logging.getLogger("aion.whatsapp.media")

# Message types we ingest; audio/video/sticker get a polite "not supported"
# reply (voice notes need STT, planned for phase 3).
SUPPORTED_INBOUND_TYPES = ("image", "document")

# Meta caps inbound media at 100 MB (larger files arrive as error 131052) and
# documents sent by us at 100 MB; images sent as ``image`` at 5 MB.
META_MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
META_MAX_IMAGE_BYTES = 5 * 1024 * 1024

DEFAULT_MAX_OUTBOUND_FILES = 5

# Explicit extensions for the MIME types WhatsApp delivers: ``save_upload``
# infers the MIME back from the extension, so a correct one matters.
_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}

# Outbound: images WhatsApp renders inline (``type: image``).
_INLINE_IMAGE_MIMES = frozenset({"image/jpeg", "image/png"})
# Outbound: document MIME types the Cloud API media upload accepts.
_DOCUMENT_MIMES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)

# Output folders scanned around a turn, and subtrees that never hold
# deliverables: artifact version history, offloaded tool results and the
# per-page text extracted by PDF auto-ingest.
_OUTPUT_ROOTS = ("workspace", "derived")
_SKIPPED_PREFIXES = (
    "workspace/.versions/",
    "derived/tool_results/",
    "derived/docs/",
)


class UnsupportedMedia(Exception):
    """Inbound media type we do not process (audio, video, sticker, ...)."""


class MediaIngestError(Exception):
    """Inbound media could not be downloaded or stored."""


# ---------------------------------------------------------------------------
# Env configuration
# ---------------------------------------------------------------------------


def media_enabled() -> bool:
    """``AION_WHATSAPP_MEDIA`` (default on): kill switch for inbound/outbound media."""
    raw = (os.getenv("AION_WHATSAPP_MEDIA") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name) or default))
    except ValueError:
        return default


def max_inbound_bytes() -> int:
    """Same limit as chat-ui uploads, never above what Meta can deliver."""
    upload_limit = _env_int("AION_UPLOAD_MAX_BYTES", 50 * 1024 * 1024, 1)
    return min(upload_limit, META_MAX_DOCUMENT_BYTES)


def max_outbound_files() -> int:
    """Generated files pushed per turn; the rest is reachable via the chat-ui link."""
    return _env_int("AION_WHATSAPP_MAX_OUTBOUND_FILES", DEFAULT_MAX_OUTBOUND_FILES)


def max_outbound_bytes() -> int:
    return min(
        _env_int("AION_WHATSAPP_MAX_OUTBOUND_BYTES", META_MAX_DOCUMENT_BYTES, 1),
        META_MAX_DOCUMENT_BYTES,
    )


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------


def _extension_for(mime: Optional[str]) -> str:
    base = (mime or "").split(";")[0].strip().lower()
    return _EXT_BY_MIME.get(base) or mimetypes.guess_extension(base or "") or ""


def inbound_filename(msg_type: str, media: InboundMedia) -> str:
    """Filename used to store an inbound media.

    Documents keep the user's filename (adding an extension when missing,
    since ``save_upload`` derives the MIME from it); photos have no name in
    WhatsApp, so they get a timestamped one.
    """
    ext = _extension_for(media.mime_type)
    if msg_type == "document" and media.filename:
        name = os.path.basename(media.filename)
        if "." not in name.strip(".") and ext:
            name += ext
        return name
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = "whatsapp" if msg_type == "image" else "documento"
    return f"{prefix}_{stamp}{ext}"


def _sha256_matches(data: bytes, expected: Optional[str]) -> bool:
    """Compare with Meta's ``sha256`` (hex or base64, the docs don't specify)."""
    if not expected:
        return True
    digest = hashlib.sha256(data).digest()
    candidates = {
        digest.hex(),
        base64.b64encode(digest).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    }
    return expected.strip() in candidates or expected.strip().lower() in candidates


async def _download(
    client: GraphClient, media: InboundMedia, phone_number_id: Optional[str]
) -> bytes:
    """Download the media bytes, refreshing the (5-minute) URL once if needed.

    The webhook ``url`` is used when present and on a Meta host; otherwise, or
    when it has expired (message queued behind a long turn, resumed after a
    restart), the URL is re-fetched with ``GET /{media-id}``.
    """
    limit = max_inbound_bytes()
    url = media.url if is_allowed_media_url(media.url) else None
    refreshed = False
    while True:
        if not url:
            info = await client.get_media(media.id, phone_number_id=phone_number_id)
            refreshed = True
            size = info.get("file_size")
            if isinstance(size, int) and size > limit:
                raise MediaTooLarge("Media too large")
            url = info.get("url")
            if not url:
                raise GraphError("Media URL missing")
        try:
            return await client.download_media(url, max_bytes=limit)
        except MediaTooLarge:
            raise
        except GraphError as e:
            # 401/403/404 on the lookaside URL = expired link: retry once
            # with a fresh one from the Graph API.
            if refreshed or e.status not in (401, 403, 404):
                raise
            url = None


async def ingest_inbound_media(
    client: GraphClient,
    *,
    tenant_id: str,
    phone_number_id: Optional[str],
    conversation_id: str,
    msg_type: str,
    media: InboundMedia,
) -> Dict[str, Any]:
    """Download an inbound image/document and store it in the conversation.

    Mirrors ``POST /v1/conversations/{id}/files``: ``save_upload`` (uploads/),
    legacy Word conversion, PDF auto-ingest in background and a best-effort
    copy on the storage backend. Returns the upload metadata, usable as an
    ``AttachmentRef`` in ``turn_attachments``.

    Raises ``UnsupportedMedia``, ``MediaTooLarge`` or ``MediaIngestError``.
    """
    if msg_type not in SUPPORTED_INBOUND_TYPES:
        raise UnsupportedMedia(msg_type)
    try:
        data = await _download(client, media, phone_number_id)
    except MediaTooLarge:
        raise
    except GraphError as e:
        raise MediaIngestError(str(e)) from e
    if not _sha256_matches(data, media.sha256):
        # Bytes come from a Meta host over TLS with our token, and the webhook
        # is signature-checked: log the mismatch instead of losing the file
        # (Meta does not document the hash encoding).
        logger.warning("WhatsApp media %s: sha256 mismatch", media.id)

    filename = inbound_filename(msg_type, media)
    try:
        meta = await asyncio.to_thread(save_upload, conversation_id, filename, data)
    except ValueError as e:  # over AION_UPLOAD_MAX_BYTES
        raise MediaTooLarge(str(e)) from e
    meta = await apply_legacy_word_conversion(conversation_id, meta)
    schedule_auto_ingest(conversation_id, meta)

    # Same object-storage copy as the v1 upload endpoint (best effort).
    key = (
        f"{tenant_id}/conversations/{conversation_id}/uploads/"
        f"{uuid.uuid4().hex[:12]}_{meta.get('name', 'file')}"
    )
    try:
        await asyncio.to_thread(
            get_storage_backend().put_bytes,
            key,
            data,
            meta.get("mime") or "application/octet-stream",
        )
        meta["storage_key"] = key
    except Exception:
        meta["storage_key"] = None
    return meta


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------

OutputSnapshot = Dict[str, Tuple[int, int]]


def snapshot_outputs(session_id: str) -> OutputSnapshot:
    """``{relative_path: (mtime_ns, size)}`` of the files in the output folders."""
    root = session_root(session_id)
    out: OutputSnapshot = {}
    for top in _OUTPUT_ROOTS:
        base = root / top
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(_SKIPPED_PREFIXES):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            out[rel] = (st.st_mtime_ns, st.st_size)
    return out


def collect_new_outputs(before: OutputSnapshot, after: OutputSnapshot) -> List[str]:
    """Deliverables created or modified during the turn, oldest first."""
    changed = [
        rel
        for rel, stat in after.items()
        if before.get(rel) != stat and is_user_facing_generated_file(rel)
    ]
    return sorted(changed, key=lambda rel: (after[rel][0], rel))


def outbound_kind(mime: str, size: int) -> Optional[Tuple[str, str]]:
    """``(message type, upload MIME)`` for a generated file, ``None`` if not sendable.

    jpeg/png up to 5 MB go inline as ``image``; Meta-supported documents as
    ``document``; other text files (csv, md, html, ...) as ``text/plain``
    documents, keeping the original filename/extension.
    """
    if size > max_outbound_bytes():
        return None
    if mime in _INLINE_IMAGE_MIMES:
        return ("image", mime) if size <= META_MAX_IMAGE_BYTES else ("document", mime)
    if mime in _DOCUMENT_MIMES:
        return ("document", mime)
    if mime.startswith("text/"):
        return ("document", "text/plain")
    return None


async def send_outputs(
    replier: Any, session_id: str, files: List[str]
) -> Tuple[int, int]:
    """Send generated files through ``replier`` (``dispatcher._Replier``).

    At most ``AION_WHATSAPP_MAX_OUTBOUND_FILES`` files are pushed. Returns
    ``(sent, left_out)``: ``left_out`` counts files over the limit, too large,
    of an unsupported type or rejected by Meta, which the caller announces
    with a link to the conversation in the chat-ui.
    """
    root = session_root(session_id)
    budget = max_outbound_files()
    sent = 0
    left_out = 0
    for rel in files:
        if sent >= budget:
            left_out += 1
            continue
        path = root / rel
        try:
            size = path.stat().st_size
        except OSError:
            continue
        mime = (
            mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        ).lower()
        kind = outbound_kind(mime, size)
        if kind is None:
            left_out += 1
            continue
        try:
            data = await asyncio.to_thread(path.read_bytes)
            await replier.send_media(kind[0], data, kind[1], path.name)
            sent += 1
        except (GraphError, OSError) as e:
            logger.warning("WhatsApp: sending generated file failed: %s", e)
            left_out += 1
    return sent, left_out


__all__ = [
    "MediaIngestError",
    "MediaTooLarge",
    "UnsupportedMedia",
    "collect_new_outputs",
    "ingest_inbound_media",
    "media_enabled",
    "outbound_kind",
    "send_outputs",
    "snapshot_outputs",
]
