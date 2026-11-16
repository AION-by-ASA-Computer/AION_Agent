"""Text extraction and pagination for files read from a share.

Delegates format handling (PDF/DOCX/XLSX/CSV/text) to
:func:`src.doc_processor.extract_text_from_bytes` and adds the windowing the
agent needs to read large files in pieces without flooding its context.
"""

from __future__ import annotations

import mimetypes
from typing import Any, Dict

from src.doc_processor import extract_text_from_bytes

_BINARY_HINT = (
    "No extractable text (scanned PDF, image or unsupported format). "
    "Use smb_copy_to_session and then OCR/sandbox tools on the copy."
)


def extract_text(
    content: bytes, filename: str, max_chars: int = 20000, offset_chars: int = 0
) -> Dict[str, Any]:
    """Return a window of the file text.

    Result keys: ``text``, ``total_chars``, ``truncated``, ``next_offset``
    (``None`` when the end was reached) and, if nothing could be extracted,
    ``hint`` pointing to the OCR workflow.
    """
    mime = mimetypes.guess_type(filename)[0] or ""
    full = extract_text_from_bytes(content, filename, mime)
    unsupported = full.startswith("(Formato non supportato") or full.startswith(
        "(Error while extracting"
    )
    if unsupported or not full.strip():
        return {
            "text": "",
            "total_chars": 0,
            "truncated": False,
            "next_offset": None,
            "hint": _BINARY_HINT,
        }
    start = max(0, int(offset_chars))
    end = start + max(1, int(max_chars))
    truncated = end < len(full)
    return {
        "text": full[start:end],
        "total_chars": len(full),
        "truncated": truncated,
        "next_offset": end if truncated else None,
    }
