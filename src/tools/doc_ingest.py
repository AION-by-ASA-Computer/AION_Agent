"""Page-by-page ingestion of documents into the session ``derived/docs`` tree.

The artefact layout is one text file per page. That single choice is what makes
large documents workable:

* ``sandbox_grep_content`` silently skips files above ``AION_GREP_MAX_FILE_BYTES``
  (500 KB); single pages stay orders of magnitude below it, so a long decree can
  never be searched into a false negative.
* The page number travels in the file name, so a grep hit already carries the
  citation the caller needs.
* ``read_file_chunk`` loads a whole file before slicing it, so reading one page
  costs kilobytes instead of the entire document.

Extraction is idempotent, concurrent, and deadline-aware: pages already on disk are skipped,
OCR is executed with parallel worker concurrency (Semaphore), and a run that hits
``budget_sec`` returns ``partial`` plus ``resume_from`` instead of being killed by the MCP bridge timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("aion.doc_ingest")

__all__ = ["ingest_document", "slugify_document_name", "DOCS_SUBDIR"]

DOCS_SUBDIR = "derived/docs"

# Uploads are stored with a random hex prefix; it carries no meaning for the slug.
_UPLOAD_PREFIX_RE = re.compile(r"^[0-9a-f]{6,}_")
_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Below this many characters a page is treated as having no usable text layer.
DEFAULT_MIN_TEXT_CHARS = 60
DEFAULT_OCR_DPI = int(os.getenv("AION_OCR_DPI", "150"))
DEFAULT_OCR_CONCURRENCY = int(os.getenv("AION_OCR_CONCURRENCY", "6"))
DEFAULT_OCR_FORMAT = os.getenv("AION_OCR_FORMAT", "jpeg")
DEFAULT_OCR_QUALITY = int(os.getenv("AION_OCR_JPEG_QUALITY", "85"))

_EXCERPT_CHARS = 400
_MAX_LISTED_EMPTY_PAGES = 50

OcrCallback = Callable[[int, bytes, str], Awaitable[str]]


def slugify_document_name(name: str) -> str:
    """Stable, filesystem-safe slug for a document file name."""
    stem = Path(name).stem
    stem = _UPLOAD_PREFIX_RE.sub("", stem)
    slug = _NON_SLUG_RE.sub("_", stem.lower()).strip("_")
    return slug or "document"


def _page_filename(page_no: int) -> str:
    return f"p{page_no:04d}.txt"


def _open_pdf(path: Path):
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover - older PyMuPDF only exposes `fitz`
        import fitz as pymupdf  # type: ignore
    return pymupdf.open(str(path))


def _rebuild_full_text(
    pages_dir: Path, full_path: Path, page_numbers: list[int]
) -> int:
    """Concatenate page files with explicit markers, streaming to avoid buffering."""
    written = 0
    with full_path.open("w", encoding="utf-8") as out:
        for page_no in page_numbers:
            page_file = pages_dir / _page_filename(page_no)
            if not page_file.is_file():
                continue
            header = f"\n=== PAGE {page_no} ===\n"
            out.write(header)
            body = page_file.read_text(encoding="utf-8", errors="replace")
            out.write(body)
            written += len(body)
    return written


async def _extract_single_page(
    doc: Any,
    page_no: int,
    pages_dir: Path,
    *,
    ocr_mode: str,
    ocr_page: Optional[OcrCallback],
    min_text_chars: int,
    ocr_dpi: int,
    ocr_format: str,
    ocr_quality: int,
    sem: asyncio.Semaphore,
) -> Dict[str, Any]:
    """Process one PDF page (native text extraction or concurrent OCR)."""
    target = pages_dir / _page_filename(page_no)

    try:
        page = doc.load_page(page_no - 1)
    except Exception as exc:
        err_msg = f"[Error loading page {page_no}: {exc}]"
        target.write_text(err_msg, encoding="utf-8")
        return {
            "page_no": page_no,
            "text": err_msg,
            "used_ocr": False,
            "ocr_failed": True,
            "is_empty": False,
        }

    text = ""
    if ocr_mode != "always":
        try:
            text = page.get_text("text") or ""
        except Exception:
            text = ""

    used_ocr = False
    ocr_failed = False
    needs_ocr = ocr_mode == "always" or (
        ocr_mode == "auto" and len(text.strip()) < min_text_chars
    )

    if needs_ocr and ocr_page is not None:
        try:
            pixmap = page.get_pixmap(dpi=ocr_dpi)
            if ocr_format.lower() in ("jpeg", "jpg"):
                img_bytes = pixmap.tobytes("jpeg", jpg_quality=ocr_quality)
                mime = "image/jpeg"
            else:
                img_bytes = pixmap.tobytes("png")
                mime = "image/png"

            async with sem:
                ocr_text = await ocr_page(page_no, img_bytes, mime)
                if ocr_text and ocr_text.strip():
                    text = ocr_text
                    used_ocr = True
        except Exception as exc:
            if not text.strip():
                text = f"[OCR failed for page {page_no}: {exc}]"
                ocr_failed = True

    target.write_text(text, encoding="utf-8")
    is_empty = not bool(text.strip()) and not ocr_failed

    return {
        "page_no": page_no,
        "text": text,
        "used_ocr": used_ocr,
        "ocr_failed": ocr_failed,
        "is_empty": is_empty,
    }


async def ingest_document(
    src_path: Path,
    session_root: Path,
    *,
    first_page: int = 1,
    last_page: int = 0,
    ocr_mode: str = "auto",
    budget_sec: float = 90.0,
    force: bool = False,
    write_full: bool = True,
    ocr_page: Optional[OcrCallback] = None,
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
    ocr_dpi: int = DEFAULT_OCR_DPI,
    ocr_concurrency: int = DEFAULT_OCR_CONCURRENCY,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Extract ``src_path`` into ``<session_root>/derived/docs/<slug>/pages``.

    ``ocr_mode`` is one of ``auto`` (OCR only pages whose text layer is shorter
    than ``min_text_chars``), ``never`` or ``always``. OCR is performed concurrently
    through ``ocr_page`` with ``ocr_concurrency`` parallel slots.
    """
    started = clock()

    if ocr_mode not in ("auto", "never", "always"):
        return {
            "ok": False,
            "error": "invalid_ocr_mode",
            "message": f"ocr_mode must be auto|never|always, got {ocr_mode!r}",
        }
    if not src_path.is_file():
        return {
            "ok": False,
            "error": "not_a_file",
            "message": f"{src_path.name} is not a readable file",
        }

    slug = slugify_document_name(src_path.name)
    root = session_root / DOCS_SUBDIR / slug
    pages_dir = root / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc = _open_pdf(src_path)
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as JSON
        return {
            "ok": False,
            "error": "open_failed",
            "message": f"Cannot open {src_path.name}: {exc}",
        }

    try:
        pages_total = doc.page_count
        start = max(1, int(first_page or 1))
        end = int(last_page) if last_page and int(last_page) > 0 else pages_total
        end = min(end, pages_total)
        if start > end:
            return {
                "ok": False,
                "error": "empty_range",
                "message": f"first_page={start} is past the last page ({pages_total})",
            }

        title_guess = ""
        try:
            title_guess = (doc.metadata or {}).get("title") or ""
        except Exception:  # noqa: BLE001 - metadata is best effort
            title_guess = ""

        written = 0
        skipped = 0
        text_layer_pages = 0
        ocr_pages = 0
        chars_total = 0
        empty_pages: list[int] = []
        ocr_failed_pages: list[int] = []
        first_excerpt = ""
        partial = False
        resume_from: Optional[int] = None

        concurrency = max(1, ocr_concurrency)
        sem = asyncio.Semaphore(concurrency)
        batch_size = max(1, concurrency)

        pages_to_process = list(range(start, end + 1))
        idx = 0

        while idx < len(pages_to_process):
            # Collect up to batch_size pages that fit within the budget
            batch_page_numbers = []
            while idx < len(pages_to_process) and len(batch_page_numbers) < batch_size:
                pno = pages_to_process[idx]
                if clock() - started >= budget_sec:
                    partial = True
                    resume_from = pno
                    break
                batch_page_numbers.append(pno)
                idx += 1

            if not batch_page_numbers:
                break

            pending_tasks = []
            for pno in batch_page_numbers:
                target = pages_dir / _page_filename(pno)
                if target.is_file() and not force:
                    body = target.read_text(encoding="utf-8", errors="replace")
                    should_reextract_with_ocr = (
                        ocr_mode == "always"
                        or (ocr_mode == "auto" and len(body.strip()) < min_text_chars)
                    )
                    if not should_reextract_with_ocr:
                        skipped += 1
                        chars_total += len(body)
                        if not body.strip():
                            empty_pages.append(pno)
                        if pno == start and not first_excerpt:
                            first_excerpt = body.strip()[:_EXCERPT_CHARS]
                        continue

                pending_tasks.append(
                    _extract_single_page(
                        doc,
                        pno,
                        pages_dir,
                        ocr_mode=ocr_mode,
                        ocr_page=ocr_page,
                        min_text_chars=min_text_chars,
                        ocr_dpi=ocr_dpi,
                        ocr_format=DEFAULT_OCR_FORMAT,
                        ocr_quality=DEFAULT_OCR_QUALITY,
                        sem=sem,
                    )
                )

            if pending_tasks:
                results = await asyncio.gather(*pending_tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        logger.warning("Page extraction error in batch: %s", res)
                        continue
                    pno = res["page_no"]
                    text = res["text"]
                    written += 1
                    chars_total += len(text)
                    if res["ocr_failed"]:
                        ocr_failed_pages.append(pno)
                    elif res["used_ocr"]:
                        ocr_pages += 1
                    elif not res["is_empty"]:
                        text_layer_pages += 1
                    else:
                        empty_pages.append(pno)

                    if pno == start and not first_excerpt:
                        first_excerpt = text.strip()[:_EXCERPT_CHARS]

            if partial:
                break

            if idx < len(pages_to_process) and (clock() - started >= budget_sec):
                partial = True
                resume_from = pages_to_process[idx]
                break

        # Sort page tracking lists for deterministic output
        empty_pages.sort()
        ocr_failed_pages.sort()

        rel_root = f"{DOCS_SUBDIR}/{slug}"
        full_rel = None
        full_path = root / "full.txt"
        if write_full:
            _rebuild_full_text(pages_dir, full_path, list(range(1, pages_total + 1)))
            if full_path.is_file() and full_path.stat().st_size > 0:
                full_rel = f"{rel_root}/full.txt"
        else:
            full_path.unlink(missing_ok=True)

        manifest = {
            "ok": True,
            "slug": slug,
            "source": src_path.name,
            "title_guess": title_guess,
            "root": rel_root,
            "pages_total": pages_total,
            "range": [start, end],
            "pages_written": written,
            "pages_skipped_existing": skipped,
            "text_layer_pages": text_layer_pages,
            "ocr_pages": ocr_pages,
            "empty_pages": empty_pages[:_MAX_LISTED_EMPTY_PAGES],
            "empty_pages_count": len(empty_pages),
            "ocr_failed_pages": ocr_failed_pages[:_MAX_LISTED_EMPTY_PAGES],
            "ocr_failed_pages_count": len(ocr_failed_pages),
            "chars_total": chars_total,
            "partial": partial,
            "resume_from": resume_from,
            "page_file_pattern": f"{rel_root}/pages/pNNNN.txt",
            "full_text": full_rel,
            "grep_hint": (
                "sandbox_grep_content(pattern=<regex>, relative_root='derived', "
                f"glob_filter='docs/{slug}/pages/*.txt', max_matches=200) — the file "
                "name of each hit is the page number."
            ),
            "first_page_excerpt": first_excerpt,
        }
        if partial:
            manifest["next_step"] = (
                f"Budget of {budget_sec:.0f}s reached at page {resume_from}. Call "
                f"doc_ingest again with first_page={resume_from} to resume; pages "
                "already written are skipped."
            )
        elif full_rel:
            manifest["next_step"] = (
                f"The complete document text is consolidated in '{full_rel}'. "
                "Read it with sandbox_read_file_chunk or search with sandbox_grep_content. "
                "Do NOT read individual page files one by one."
            )
        else:
            manifest["next_step"] = (
                "Verify the document identity against the user request using "
                "title_guess/first_page_excerpt, then grep the pages as per grep_hint."
            )

        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001 - best effort
            pass
