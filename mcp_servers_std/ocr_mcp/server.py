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
        import pymupdf4llm

        return pymupdf4llm.to_markdown(str(path))
    except ImportError:
        return "Error pymypdf4llm not installed"


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


@mcp.tool()
async def ocr_file(
    relative_path: str,
    instruction: str = "Extract all visible text. Preserve reading order.",
    max_pages: int = 20,
) -> str:
    """
    Extract text from a session file (uploads/, derived/, workspace/).
    ALWAYS use the vision-based OCR model (vLLM/OpenAI) per la massima precisione.
    Per i PDF, elabora le pagine in parallelo.
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
            from pdf2image import convert_from_path

            # Carichiamo le impostazioni o usiamo il parametro
            limit = _env_int("AION_OCR_PDF_MAX_PAGES", max_pages)
            images = convert_from_path(str(path), first_page=1, last_page=limit)

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
                    limited_ocr(img_data, "image/jpeg", f"Page {i + 1}: {instruction}")
                )

            logger.info(
                f"Starting parallel OCR (limit 5) for {len(tasks)} pages of {path.name}"
            )
            results = await asyncio.gather(*tasks, return_exceptions=True)

            all_text = []
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    all_text.append(f"--- PAGE {i + 1} ERROR ---\n{res}")
                else:
                    all_text.append(f"--- PAGE {i + 1} ---\n{res}")

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
