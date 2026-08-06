"""Fire-and-forget PDF text-layer extraction triggered on upload.

Runs ``ingest_document`` in a worker thread so PyMuPDF does not block the FastAPI
event loop (mandatory with ``--workers 1``).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from src.session_workspace import safe_resolve, session_root
from src.tools.doc_ingest import DOCS_SUBDIR, ingest_document, slugify_document_name

logger = logging.getLogger("aion.doc_auto_ingest")

_PDF_MIME = "application/pdf"


def auto_ingest_enabled() -> bool:
    return os.getenv("AION_DOC_AUTO_INGEST", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _auto_ingest_max_pages() -> int:
    try:
        return max(1, int(os.getenv("AION_DOC_AUTO_INGEST_MAX_PAGES", "500")))
    except ValueError:
        return 500


def _auto_ingest_budget_sec() -> float:
    try:
        return float(os.getenv("AION_DOC_AUTO_INGEST_BUDGET_SEC", "120"))
    except ValueError:
        return 120.0


def manifest_path(session_id: str, slug: str) -> Path:
    return session_root(session_id) / DOCS_SUBDIR / slug / "manifest.json"


def load_manifest(session_id: str, relative_path: str) -> dict[str, Any] | None:
    """Return ingest manifest for an uploaded PDF if extraction has run."""
    slug = slugify_document_name(Path(relative_path).name)
    path = manifest_path(session_id, slug)
    if not path.is_file():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ingest_sync(session_id: str, relative_path: str) -> dict[str, Any]:
    """Blocking ingest loop with resume until complete or page cap."""
    import asyncio

    path = safe_resolve(session_id, relative_path, must_exist=True)
    root = session_root(session_id)
    max_pages = _auto_ingest_max_pages()
    budget = _auto_ingest_budget_sec()
    resume_from = 1
    manifest: dict[str, Any] = {"ok": False}

    async def _run_once(start: int) -> dict[str, Any]:
        return await ingest_document(
            path,
            root,
            first_page=start,
            last_page=max_pages,
            ocr_mode="never",
            budget_sec=budget,
            force=False,
            write_full=False,
        )

    for _ in range(50):
        manifest = asyncio.run(_run_once(resume_from))
        if not manifest.get("ok"):
            return manifest
        if not manifest.get("partial"):
            break
        nxt = manifest.get("resume_from")
        if not nxt or int(nxt) <= resume_from:
            break
        resume_from = int(nxt)

    return manifest


async def run_auto_ingest_background(session_id: str, relative_path: str, mime: str) -> None:
    """Schedule-safe background ingest for one uploaded PDF."""
    if not auto_ingest_enabled():
        return
    if (mime or "").split(";")[0].strip().lower() != _PDF_MIME:
        return

    try:
        manifest = await asyncio.to_thread(_ingest_sync, session_id, relative_path)
    except Exception as exc:
        logger.exception(
            "auto_ingest failed session=%s path=%s: %s",
            session_id[:8],
            relative_path,
            exc,
        )
        return

    if manifest.get("ok"):
        slug = str(manifest.get("slug") or "")
        logger.info(
            "auto_ingest complete session=%s slug=%s pages=%s partial=%s",
            session_id[:8],
            slug,
            manifest.get("pages_written"),
            manifest.get("partial"),
        )
    else:
        logger.warning(
            "auto_ingest error session=%s path=%s: %s",
            session_id[:8],
            relative_path,
            manifest,
        )


def schedule_auto_ingest(
    session_id: str,
    upload_meta: dict[str, Any],
) -> None:
    """Fire-and-forget task for a single ``save_upload`` result."""
    mime = str(upload_meta.get("mime") or "")
    rel = str(upload_meta.get("relative_path") or "")
    if not rel:
        return
    try:
        asyncio.get_running_loop().create_task(
            run_auto_ingest_background(session_id, rel, mime)
        )
    except RuntimeError:
        logger.debug("no running loop; skip auto_ingest for %s", rel)
