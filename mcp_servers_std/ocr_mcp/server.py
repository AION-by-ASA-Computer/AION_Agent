"""
MCP OCR: chiama il servizio OpenAI-compatibile (es. vLLM GLM-OCR) su file nella sessione.
Richiede AION_CHAT_SESSION_ID (impostato dal pool MCP).
"""

from __future__ import annotations

import base64
import os
import sys
import mimetypes
import httpx
import asyncio

_ocr_lock = asyncio.Lock()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from fastmcp import FastMCP

mcp = FastMCP("AION OCR")


import logging

logger = logging.getLogger("mcp_ocr")
logging.basicConfig(level=logging.INFO)


def _require_session() -> str:
    sid = os.environ.get("AION_CHAT_SESSION_ID", "").strip()
    if not sid:
        logger.error("AION_CHAT_SESSION_ID not set")
        raise RuntimeError("AION_CHAT_SESSION_ID not set")
    return sid


def _is_advanced_ocr_enabled() -> bool:
    base = os.environ.get("AION_OCR_BASE_URL", "").strip()
    key = os.environ.get("AION_OCR_API_KEY", "").strip()
    logger.info(
        "OCR configuration loaded (base_set=%s, api_key_set=%s)",
        bool(base),
        bool(key and key != "EMPTY"),
    )
    if not base or not key or key == "EMPTY":
        return False
    return True


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name, "").strip()
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _extract_pdf_via_pymu4llm(path) -> str:
    try:
        import fitz

        doc = fitz.open(str(path))
        pages_text = []
        for i, page in enumerate(doc):
            t = page.get_text("text").strip()
            if t:
                pages_text.append(f"--- PAGE {i + 1} ---\n{t}")
            else:
                try:
                    import pymupdf4llm

                    pages_text.append(
                        f"--- PAGE {i + 1} ---\n"
                        + pymupdf4llm.to_markdown(str(path), pages=[i])
                    )
                except Exception:
                    pass
        if pages_text:
            return "\n\n".join(pages_text)
    except Exception as e:
        logger.warning(f"fitz text extraction failed: {e}")

    try:
        import pymupdf4llm

        return pymupdf4llm.to_markdown(str(path))
    except ImportError:
        return "Error pymupdf4llm not installed"


def _extract_image_via_pytesseract(path) -> str:
    try:
        import pytesseract

        return pytesseract.image_to_string(str(path))
    except Exception as e:
        raise RuntimeError(str(e))


async def _ocr_via_api_async(
    image_bytes: bytes,
    mime: str,
    instruction: str,
    client: httpx.AsyncClient | None = None,
) -> str:
    import httpx

    base = os.environ.get("AION_OCR_BASE_URL", "http://localhost:8000/ocr/v1").rstrip(
        "/"
    )
    model = os.environ.get("AION_OCR_MODEL", "")
    key = os.environ.get("AION_OCR_API_KEY", "EMPTY")
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": min(_env_int("AION_OCR_MAX_TOKENS", 4096), 4096),
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}

    try:
        async with _ocr_lock:
            if client:
                r = await client.post(
                    f"{base}/chat/completions", json=payload, headers=headers
                )
                r.raise_for_status()
                data = r.json()
            else:
                async with httpx.AsyncClient(
                    timeout=_env_float("AION_OCR_TIMEOUT", 120.0)
                ) as client_new:
                    r = await client_new.post(
                        f"{base}/chat/completions", json=payload, headers=headers
                    )
                    r.raise_for_status()
                    data = r.json()
    except httpx.HTTPStatusError as e:
        err_msg = f"HTTP {e.response.status_code} from OCR server: {e.response.text}"
        logger.error(err_msg)
        raise RuntimeError(err_msg) from e

    choices = data.get("choices") or []
    if not choices:
        return f"Risposta OCR vuota: {data!r}"
    content = choices[0].get("message", {}).get("content")
    return content if isinstance(content, str) else str(content)


def _clamp_ingest_budget(requested: float) -> float:
    """Keep the internal deadline safely below the MCP bridge timeout."""
    bridge = _env_float("AION_MCP_TOOL_RESULT_TIMEOUT", 120.0)
    ceiling = max(10.0, bridge - 25.0)
    try:
        value = float(requested)
    except (TypeError, ValueError):
        value = 90.0
    if value <= 0:
        value = ceiling
    return min(max(value, 10.0), ceiling)


@mcp.tool()
async def doc_ingest(
    relative_path: str,
    first_page: int = 1,
    last_page: int = 0,
    ocr_mode: str = "auto",
    budget_sec: float = 90.0,
    force: bool = False,
    write_full: bool = False,
) -> str:
    """
    Extract a PDF into one text file per page under derived/docs/<slug>/pages/.

    This is the entry point for ANY multi-page document. Prefer it over ocr_file and
    over custom extraction scripts: it never loads the whole document in memory, it
    skips pages already extracted, and if it runs out of time it returns
    ``partial: true`` with ``resume_from`` so the next call continues where it stopped.

    ``ocr_mode``: ``auto`` runs OCR only on pages with no usable text layer (cheap on
    born-digital PDFs), ``never`` disables it, ``always`` forces OCR on every page.
    ``write_full`` additionally concatenates everything into ``full.txt``; leave it off
    unless you need sequential reading, because a single large file is skipped by
    ``sandbox_grep_content`` above AION_GREP_MAX_FILE_BYTES.

    Returns a small JSON manifest: page counts, empty pages, the grep pattern to use,
    and an excerpt of the first page to confirm the document is the one requested.
    """
    import json

    from src.session_workspace import ensure_session_dirs, safe_resolve, session_root
    from src.tools.doc_ingest import ingest_document

    sid = _require_session()
    ensure_session_dirs(sid)
    try:
        path = safe_resolve(sid, relative_path, must_exist=True)
    except Exception as e:
        return json.dumps(
            {"ok": False, "error": "path_error", "message": str(e)},
            ensure_ascii=False,
        )

    async def _ocr_page(page_no: int, image_bytes: bytes, mime: str) -> str:
        return await _ocr_via_api_async(
            image_bytes,
            mime,
            f"Page {page_no}: Extract all visible text. Preserve reading order.",
        )

    use_ocr = ocr_mode != "never" and _is_advanced_ocr_enabled()

    try:
        manifest = await ingest_document(
            path,
            session_root(sid),
            first_page=first_page,
            last_page=last_page,
            ocr_mode=ocr_mode,
            budget_sec=_clamp_ingest_budget(budget_sec),
            force=force,
            write_full=write_full,
            ocr_page=_ocr_page if use_ocr else None,
        )
    except Exception as e:
        logger.exception("doc_ingest failed for %s", relative_path)
        return json.dumps(
            {"ok": False, "error": "ingest_failed", "message": str(e)},
            ensure_ascii=False,
        )

    if manifest.get("ok") and not use_ocr and manifest.get("empty_pages_count"):
        manifest["warning"] = (
            f"{manifest['empty_pages_count']} page(s) have no text layer and OCR is "
            "unavailable (ocr_mode=never or OCR service not configured). Those pages "
            "are empty in the extraction."
        )
    return json.dumps(manifest, ensure_ascii=False)


@mcp.tool()
async def ocr_file(
    relative_path: str,
    instruction: str = "Extract all visible text. Preserve reading order.",
    max_pages: int = 20,
    first_page: int = 1,
    last_page: int = 0,
) -> str:
    """
    Extract text from a session file (uploads/, derived/, workspace/) via vision OCR.

    For multi-page PDFs prefer ``doc_ingest``: it is far cheaper, writes one file per
    page and resumes after a timeout. Use ``ocr_file`` for single images or a small
    page range of a scanned PDF.

    Page range (PDF only): ``first_page``/``last_page`` are 1-based and inclusive.
    Leave ``last_page=0`` to read ``max_pages`` pages starting at ``first_page``.
    """
    from src.session_workspace import ensure_session_dirs, safe_resolve
    import asyncio
    from io import BytesIO

    sid = _require_session()
    ensure_session_dirs(sid)
    logger.info(f"OCR request for {relative_path} in session {sid}")
    try:
        path = safe_resolve(sid, relative_path, must_exist=True)
    except Exception as e:
        logger.error(f"Path error: {e}")
        return f"Path error: {e}"
    if not path.is_file():
        return "Path is not a file."

    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"

    if not _is_advanced_ocr_enabled():
        logger.info("Advanced OCR is disabled. Using local parsers.")
        if mime == "application/pdf":
            try:
                text = _extract_pdf_via_pymu4llm(path)
                logger.info(
                    f"pymu4llm extraction success for {path.name}: {len(text)} chars"
                )
                return text
            except Exception as e:
                logger.exception("pymu4llm extraction failed")
                return f"Error during local PDF text extraction (pymu4llm): {e}"
        elif mime.startswith("image/"):
            try:
                text = _extract_image_via_pytesseract(path)
                logger.info(
                    f"pytesseract extraction success for {path.name}: {len(text)} chars"
                )
                return text
            except Exception as e:
                logger.warning(f"pytesseract extraction failed: {e}")
                return (
                    f"Advanced OCR is disabled. Local extraction via pytesseract failed: {e}. "
                    "Make sure the 'tesseract' binary is installed on the system."
                )
        else:
            return f"Advanced OCR is disabled. Local extraction is not supported for MIME type: {mime}."

    if mime == "application/pdf":
        try:
            native_text = ""
            try:
                import fitz

                doc_fitz = fitz.open(str(path))
                pages_native = []
                for idx, page_obj in enumerate(doc_fitz):
                    nt = page_obj.get_text("text").strip()
                    if nt:
                        pages_native.append(f"--- NATIVE TEXT PAGE {idx + 1} ---\n{nt}")
                if pages_native:
                    native_text = "\n\n".join(pages_native)
            except Exception as ex_fitz:
                logger.warning(f"Native fitz text extraction warning: {ex_fitz}")

            from pdf2image import convert_from_path

            # Carichiamo le impostazioni o usiamo il parametro
            span = _env_int("AION_OCR_PDF_MAX_PAGES", max_pages)
            start = max(1, int(first_page or 1))
            if last_page and int(last_page) >= start:
                end = int(last_page)
            else:
                end = start + max(1, span) - 1
            # Never let an explicit range exceed the configured per-call page budget.
            end = min(end, start + max(1, span) - 1)
            images = convert_from_path(str(path), first_page=start, last_page=end)

            # Limit parallel calls to avoid overloading the OCR server
            sem = asyncio.Semaphore(5)

            async def limited_ocr(img_data, mime, page_instr):
                async with sem:
                    return await _ocr_via_api_async(img_data, mime, page_instr)

            tasks = []
            for i, img in enumerate(images):
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=85)
                img_data = buf.getvalue()
                tasks.append(
                    limited_ocr(
                        img_data, "image/jpeg", f"Page {start + i}: {instruction}"
                    )
                )

            logger.info(
                "Starting parallel OCR (limit 5) for pages %d-%d of %s",
                start,
                start + len(tasks) - 1,
                path.name,
            )
            results = await asyncio.gather(*tasks, return_exceptions=True)

            all_text = []
            if native_text:
                all_text.append(native_text)

            for i, res in enumerate(results):
                page_no = start + i
                if isinstance(res, Exception):
                    all_text.append(f"--- OCR PAGE {i + 1} ERROR ---\n{res}")
                else:
                    all_text.append(f"--- OCR PAGE {i + 1} ---\n{res}")

            return "\n\n".join(all_text)
        except Exception as e:
            logger.exception("PDF OCR failed")
            return f"Error during PDF OCR: {e}"

    if mime.startswith("image/"):
        data = path.read_bytes()
        limit_bytes = _env_int("AION_OCR_MAX_IMAGE_BYTES", 20 * 1024 * 1024)
        if len(data) > limit_bytes:
            return f"Image too large (max {limit_bytes} bytes)."
        try:
            res = await _ocr_via_api_async(data, mime, instruction)
            logger.info(f"OCR success for {path.name}: {len(res)} chars")
            return res
        except Exception as e:
            logger.error(f"OCR call error: {e}")
            return f"OCR call error: {e}"

    return f"MIME type not supported for OCR: {mime}. Use images (png, jpeg, webp, tiff) o PDF."


@mcp.tool()
async def pdf_evidence_crop(
    relative_path: str,
    page: int,
    bbox: dict | None = None,
    full_page: bool = False,
    dpi: int = 0,
    caption: str = "",
) -> str:
    """
    Crop a PDF page region into a PNG evidence image for Word report deliverables.

    Writes ``derived/docs/<slug>/evidence/eNNN.png`` plus a JSON sidecar with page,
    bbox, dpi, white_ratio, and caption. Use after ``doc_ingest`` + grep when you need
    a screenshot for a cited page — never attach a full-page ``pdftoppm`` dump as evidence.

    Args:
        relative_path: Session path to the PDF (e.g. ``uploads/decreto.pdf``).
        page: 1-based page number.
        bbox: Optional clip in PDF points ``{x0, y0, x1, y1}``. When omitted and
            ``full_page`` is false, the page is rendered then auto-trimmed to content.
        full_page: When true (and no bbox), keep the entire page without auto-trim.
        dpi: Render resolution (default from ``AION_PDF_EVIDENCE_DPI``, usually 200).
        caption: Required caption for the figure (e.g. ``decreto / §8.9 / pag. 101``).

    Returns JSON with ``ok``, ``png_path``, ``sidecar_path``, ``white_ratio``. Fails with
    ``too_much_whitespace`` when the result is mostly blank (full-page dump guard).
    """
    import asyncio
    import json

    from src.session_workspace import ensure_session_dirs, safe_resolve, session_root
    from src.tools.pdf_evidence import default_dpi, pdf_evidence_crop_sync

    sid = _require_session()
    ensure_session_dirs(sid)
    try:
        path = safe_resolve(sid, relative_path, must_exist=True)
    except FileNotFoundError:
        from src.session_workspace import list_dir

        pdfs = [
            row["relative_path"]
            for row in list_dir(sid, subdir="uploads")
            if str(row.get("mime", "")).endswith("pdf")
            or str(row.get("name", "")).lower().endswith(".pdf")
        ]
        hint = "Call sandbox_list_files(subdir='uploads') to list uploaded files."
        if pdfs:
            hint = (
                f"PDF not found at {relative_path!r}. Available uploads: "
                + ", ".join(pdfs[:8])
                + (" …" if len(pdfs) > 8 else "")
            )
        return json.dumps(
            {
                "ok": False,
                "error": "path_error",
                "message": f"file not found: {relative_path}",
                "hint": hint,
                "upload_pdfs": pdfs[:12],
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {"ok": False, "error": "path_error", "message": str(e)},
            ensure_ascii=False,
        )

    render_dpi = dpi if dpi and dpi > 0 else default_dpi()
    result = await asyncio.to_thread(
        pdf_evidence_crop_sync,
        path,
        session_root(sid),
        page=page,
        bbox=bbox,
        full_page=full_page,
        dpi=render_dpi,
        caption=caption,
        source_relative_path=relative_path.strip().lstrip("/"),
    )
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    import asyncio
    import traceback
    from mcp.server.stdio import stdio_server

    async def main():
        try:
            async with stdio_server() as (read_stream, write_stream):
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(),
                )
        except Exception as e:
            log = os.path.join("data", "mcp_debug.log")
            os.makedirs(os.path.dirname(log) or ".", exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n--- OCR MCP CRASH ---\n{traceback.format_exc()}\n")
            raise e

    asyncio.run(main())
