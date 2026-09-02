"""Convert legacy Word binaries (.doc) to .docx on the API host via LibreOffice."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.session_workspace import safe_resolve, session_root

logger = logging.getLogger("aion.office_convert")

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"

_LEGACY_WORD_EXTS = frozenset({".doc", ".dot", ".wps"})
_LEGACY_WORD_MIMES = frozenset(
    {
        "application/msword",
        "application/vnd.ms-word",
        "application/vnd.ms-word.document.macroenabled.12",
    }
)

_CONVERTED_SUBDIR = "derived/converted"


def office_auto_convert_enabled() -> bool:
    return os.getenv("AION_OFFICE_AUTO_CONVERT_LEGACY_WORD", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _convert_timeout_sec() -> float:
    try:
        return max(5.0, float(os.getenv("AION_OFFICE_CONVERT_TIMEOUT_SEC", "90")))
    except ValueError:
        return 90.0


def is_legacy_word_upload(filename: str, mime: str, data: bytes | None = None) -> bool:
    name = (filename or "").lower()
    ext = Path(name).suffix
    mime_l = (mime or "").split(";")[0].strip().lower()
    if ext in _LEGACY_WORD_EXTS or mime_l in _LEGACY_WORD_MIMES:
        return True
    if data is not None and ext == ".doc":
        head = data[:8]
        if head.startswith(_OLE_MAGIC):
            return True
        if head.startswith(_ZIP_MAGIC):
            return False
    return False


def is_misnamed_docx(filename: str, data: bytes) -> bool:
    """`.doc` extension but OpenXML zip payload."""
    if not (filename or "").lower().endswith(".doc"):
        return False
    return data[:4] == _ZIP_MAGIC


def find_soffice() -> str | None:
    explicit = (os.getenv("AION_SOFFICE_PATH") or "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("soffice")
    if found:
        return found
    for candidate in (
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem or "document"
    stem = re.sub(r"[^\w.\-]+", "_", stem).strip("._")
    return stem or "document"


def _copy_as_docx(session_id: str, src_rel: str, original_name: str) -> dict[str, Any]:
    src = safe_resolve(session_id, src_rel, must_exist=True)
    out_name = f"{_safe_stem(original_name)}.docx"
    out_rel = f"{_CONVERTED_SUBDIR}/{out_name}"
    out_path = safe_resolve(session_id, out_rel, must_exist=False)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out_path)
    return {
        "legacy_word": True,
        "conversion_status": "ok",
        "conversion_method": "rename_zip",
        "converted_docx_path": out_rel,
        "conversion_note": (
            "File had a .doc extension but is already OpenXML; copied as .docx."
        ),
    }


def convert_legacy_word_sync(
    session_id: str,
    upload_meta: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert a legacy Word upload to docx under derived/converted/ via LibreOffice.

    Mutates and returns ``upload_meta`` with conversion fields.
    """
    rel = str(upload_meta.get("relative_path") or "")
    original_name = str(upload_meta.get("original_name") or Path(rel).name)
    mime = str(upload_meta.get("mime") or "")

    if not rel:
        return upload_meta

    if not is_legacy_word_upload(original_name, mime):
        return upload_meta

    src = safe_resolve(session_id, rel, must_exist=True)
    data = src.read_bytes()

    if is_misnamed_docx(original_name, data):
        upload_meta.update(_copy_as_docx(session_id, rel, original_name))
        return upload_meta

    soffice = find_soffice()
    if not soffice:
        upload_meta.update(
            {
                "legacy_word": True,
                "conversion_status": "unavailable",
                "conversion_error": (
                    "LibreOffice (soffice) not found on the API host. "
                    "Install libreoffice-writer-nogui (Docker/Ubuntu) or set AION_SOFFICE_PATH."
                ),
            }
        )
        return upload_meta

    out_name = f"{_safe_stem(original_name)}.docx"
    out_rel = f"{_CONVERTED_SUBDIR}/{out_name}"
    out_path = safe_resolve(session_id, out_rel, must_exist=False)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="aion-lo-") as tmp:
        tmp_in = Path(tmp) / Path(original_name).name
        tmp_in.write_bytes(data)
        cmd = [
            soffice,
            "--headless",
            "--norestore",
            "--invisible",
            "--convert-to",
            "docx",
            "--outdir",
            tmp,
            str(tmp_in),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_convert_timeout_sec(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            upload_meta.update(
                {
                    "legacy_word": True,
                    "conversion_status": "failed",
                    "conversion_error": "LibreOffice conversion timed out",
                }
            )
            return upload_meta
        except OSError as exc:
            upload_meta.update(
                {
                    "legacy_word": True,
                    "conversion_status": "failed",
                    "conversion_error": str(exc),
                }
            )
            return upload_meta

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:500]
            logger.warning(
                "soffice convert failed session=%s file=%s rc=%s err=%s",
                session_id[:8],
                original_name,
                proc.returncode,
                err,
            )
            upload_meta.update(
                {
                    "legacy_word": True,
                    "conversion_status": "failed",
                    "conversion_error": err or f"soffice exit {proc.returncode}",
                }
            )
            return upload_meta

        produced = sorted(Path(tmp).glob("*.docx"))
        if not produced:
            upload_meta.update(
                {
                    "legacy_word": True,
                    "conversion_status": "failed",
                    "conversion_error": "LibreOffice produced no .docx output",
                }
            )
            return upload_meta

        shutil.copy2(produced[0], out_path)

    upload_meta.update(
        {
            "legacy_word": True,
            "conversion_status": "ok",
            "conversion_method": "libreoffice",
            "converted_docx_path": out_rel,
            "conversion_note": (
                f"Legacy Word converted to `{out_rel}`. "
                "Use the .docx path with skill_view('docx') / unpack workflow; "
                "do not run unpack on the original .doc binary."
            ),
        }
    )
    logger.info(
        "legacy_word_converted session=%s src=%s out=%s",
        session_id[:8],
        rel,
        out_rel,
    )
    return upload_meta


def retry_legacy_word_conversion(session_id: str, upload_rel: str) -> dict[str, Any]:
    """Re-attempt conversion (e.g. after a prior unavailable manifest)."""
    meta = {
        "relative_path": upload_rel,
        "original_name": Path(upload_rel).name,
        "mime": "application/msword",
    }
    return convert_legacy_word_sync(session_id, meta)


def conversion_manifest_path(session_id: str, upload_rel: str) -> Path:
    slug = re.sub(r"[^\w.\-]+", "_", Path(upload_rel).name).strip("._") or "upload"
    return session_root(session_id) / "derived" / "converted" / f"{slug}.json"
