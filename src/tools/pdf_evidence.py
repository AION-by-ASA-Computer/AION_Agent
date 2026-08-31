"""Crop PDF pages into evidence PNGs for Word report deliverables.

Renders a page (or clip region) via PyMuPDF, optionally auto-trims whitespace with
Pillow, and writes PNG + JSON sidecar under ``derived/docs/<slug>/evidence/``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from src.tools.doc_ingest import DOCS_SUBDIR, slugify_document_name

__all__ = ["pdf_evidence_crop_sync", "compute_white_ratio", "auto_trim_image"]

_EVIDENCE_RE = re.compile(r"^e(\d+)\.png$")
_DEFAULT_DPI = 200
_DEFAULT_MAX_WHITE_RATIO = 0.90
_DEFAULT_TRIM_THRESHOLD = 250
_DEFAULT_TRIM_PADDING = 8


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name, "").strip()
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def default_dpi() -> int:
    return max(72, _env_int("AION_PDF_EVIDENCE_DPI", _DEFAULT_DPI))


def max_white_ratio() -> float:
    return min(
        1.0,
        max(
            0.0,
            _env_float("AION_PDF_EVIDENCE_MAX_WHITE_RATIO", _DEFAULT_MAX_WHITE_RATIO),
        ),
    )


def _open_pdf(path: Path):
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover
        import fitz as pymupdf  # type: ignore
    return pymupdf.open(str(path))


def _pymupdf_module():
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover
        import fitz as pymupdf  # type: ignore
    return pymupdf


def _text_blocks_clip(pdf_page, *, padding: int = 12):
    """Union bounding box of text blocks on a PDF page (PyMuPDF points)."""
    pymupdf = _pymupdf_module()
    blocks = [
        block
        for block in pdf_page.get_text("blocks")
        if len(block) >= 7 and block[6] == 0 and str(block[4] or "").strip()
    ]
    if not blocks:
        return None
    x0 = min(block[0] for block in blocks)
    y0 = min(block[1] for block in blocks)
    x1 = max(block[2] for block in blocks)
    y1 = max(block[3] for block in blocks)
    clip = (
        pymupdf.Rect(x0 - padding, y0 - padding, x1 + padding, y1 + padding)
        & pdf_page.rect
    )
    return None if clip.is_empty else clip


def _page_text_char_count(pdf_page) -> int:
    return len((pdf_page.get_text("text") or "").strip())


def _pixmap_to_image(pixmap):
    """Convert a PyMuPDF pixmap to PIL Image (handles colorspace variants)."""
    from io import BytesIO

    from PIL import Image

    return Image.open(BytesIO(pixmap.tobytes("png")))


def _iter_rgb_pixels(rgb_image):
    """Yield ``(r, g, b)`` regardless of Pillow pixel API version."""
    if hasattr(rgb_image, "get_flattened_data"):
        data = rgb_image.get_flattened_data()
        if not data:
            return
        if isinstance(data[0], (tuple, list)):
            for px in data:
                yield int(px[0]), int(px[1]), int(px[2])
            return
        for i in range(0, len(data), 3):
            yield int(data[i]), int(data[i + 1]), int(data[i + 2])
        return
    for r, g, b in rgb_image.getdata():
        yield int(r), int(g), int(b)


def compute_white_ratio(image, *, threshold: int = _DEFAULT_TRIM_THRESHOLD) -> float:
    """Fraction of pixels at or above ``threshold`` on all RGB channels."""
    from PIL import Image

    if not isinstance(image, Image.Image):
        raise TypeError("image must be a PIL.Image")
    rgb = image.convert("RGB")
    total = 0
    white = 0
    for r, g, b in _iter_rgb_pixels(rgb):
        total += 1
        if r >= threshold and g >= threshold and b >= threshold:
            white += 1
    return (white / total) if total else 1.0


def auto_trim_image(
    image,
    *,
    padding: int = _DEFAULT_TRIM_PADDING,
    threshold: int = _DEFAULT_TRIM_THRESHOLD,
):
    """Crop to the bounding box of non-white content."""
    from PIL import Image

    if not isinstance(image, Image.Image):
        raise TypeError("image must be a PIL.Image")
    gray = image.convert("L")
    mask = gray.point(lambda p: 255 if p < threshold else 0)
    bbox = mask.getbbox()
    if not bbox:
        return image
    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - padding)
    y0 = max(0, y0 - padding)
    x1 = min(image.width, x1 + padding)
    y1 = min(image.height, y1 + padding)
    return image.crop((x0, y0, x1, y1))


def _next_evidence_index(evidence_dir: Path) -> int:
    max_idx = 0
    for path in evidence_dir.glob("e*.png"):
        match = _EVIDENCE_RE.match(path.name)
        if match:
            max_idx = max(max_idx, int(match.group(1)))
    return max_idx + 1


def _parse_bbox(raw: Any) -> Optional[tuple[float, float, float, float]]:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        return tuple(float(v) for v in raw)
    if isinstance(raw, dict):
        keys = ("x0", "y0", "x1", "y1")
        if all(k in raw for k in keys):
            return tuple(float(raw[k]) for k in keys)
    raise ValueError("bbox must be {x0,y0,x1,y1} or [x0,y0,x1,y1]")


def _relative_to_session(session_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(session_root.resolve()).as_posix()
    except ValueError:
        # Unit tests and out-of-session paths: keep a stable relative label.
        return path.name


def pdf_evidence_crop_sync(
    pdf_path: Path,
    session_root: Path,
    *,
    page: int,
    bbox: Any = None,
    full_page: bool = False,
    dpi: Optional[int] = None,
    caption: str = "",
    source_relative_path: str = "",
) -> dict:
    """Render a PDF page clip to PNG + JSON sidecar under derived/docs/<slug>/evidence/."""
    if page < 1:
        return {
            "ok": False,
            "error": "invalid_page",
            "message": f"page must be >= 1, got {page}",
        }
    if not pdf_path.is_file():
        return {
            "ok": False,
            "error": "not_a_file",
            "message": f"{pdf_path.name} is not a readable file",
        }

    render_dpi = dpi if dpi is not None else default_dpi()
    render_dpi = max(72, min(render_dpi, 600))
    white_limit = max_white_ratio()

    try:
        clip = _parse_bbox(bbox)
    except ValueError as exc:
        return {"ok": False, "error": "invalid_bbox", "message": str(exc)}

    slug = slugify_document_name(pdf_path.name)
    evidence_dir = session_root / DOCS_SUBDIR / slug / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    index = _next_evidence_index(evidence_dir)
    stem = f"e{index:03d}"
    png_path = evidence_dir / f"{stem}.png"
    sidecar_path = evidence_dir / f"{stem}.json"

    try:
        doc = _open_pdf(pdf_path)
    except Exception as exc:
        return {
            "ok": False,
            "error": "pdf_open_failed",
            "message": str(exc),
        }

    try:
        if page > doc.page_count:
            return {
                "ok": False,
                "error": "page_out_of_range",
                "message": f"page {page} exceeds document page count {doc.page_count}",
                "page_count": doc.page_count,
            }

        pdf_page = doc[page - 1]
        page_rect = pdf_page.rect
        pymupdf = _pymupdf_module()
        crop_method = "full_page" if full_page and clip is None else "bbox"
        text_chars = _page_text_char_count(pdf_page)

        def _render_clip(clip_rect, *, method: str):
            nonlocal crop_method
            if clip_rect is None or clip_rect.is_empty:
                return None
            crop_method = method
            bbox_used = [clip_rect.x0, clip_rect.y0, clip_rect.x1, clip_rect.y1]
            pix = pdf_page.get_pixmap(dpi=render_dpi, clip=clip_rect, alpha=False)
            return bbox_used, pix

        used_bbox = [page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1]
        pixmap = None
        cropped = False

        if clip is not None:
            x0, y0, x1, y1 = clip
            clip_rect = pymupdf.Rect(x0, y0, x1, y1) & page_rect
            if clip_rect.is_empty:
                return {
                    "ok": False,
                    "error": "empty_clip",
                    "message": "bbox does not intersect the page",
                }
            rendered = _render_clip(clip_rect, method="bbox")
            if rendered is None:
                return {
                    "ok": False,
                    "error": "empty_clip",
                    "message": "bbox does not intersect the page",
                }
            used_bbox, pixmap = rendered
        elif not full_page:
            text_clip = _text_blocks_clip(pdf_page)
            if text_clip is not None:
                rendered = _render_clip(text_clip, method="text_blocks")
                if rendered is not None:
                    used_bbox, pixmap = rendered
                    cropped = True
            if pixmap is None:
                pixmap = pdf_page.get_pixmap(dpi=render_dpi, alpha=False)
                used_bbox = [page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1]
                crop_method = "auto_trim"
        else:
            pixmap = pdf_page.get_pixmap(dpi=render_dpi, alpha=False)
            used_bbox = [page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1]

        image = _pixmap_to_image(pixmap)
        if clip is None and not full_page and crop_method == "auto_trim":
            image = auto_trim_image(image)
            cropped = True

        white_ratio = compute_white_ratio(image)
        # Pages with a real text layer may stay visually sparse after trim; allow a
        # slightly higher ceiling than blank full-page dumps.
        effective_white_limit = white_limit
        if crop_method in {"text_blocks", "auto_trim"} and text_chars >= 80:
            effective_white_limit = min(0.97, white_limit + 0.07)
        rel_png = _relative_to_session(session_root, png_path)
        rel_sidecar = _relative_to_session(session_root, sidecar_path)
        rel_source = source_relative_path or _relative_to_session(
            session_root, pdf_path
        )

        sidecar = {
            "page": page,
            "bbox": used_bbox,
            "dpi": render_dpi,
            "white_ratio": round(white_ratio, 4),
            "cropped": cropped,
            "crop_method": crop_method,
            "text_chars": text_chars,
            "caption": caption,
            "source_path": rel_source,
            "png_path": rel_png,
            "full_page": bool(full_page and clip is None),
        }

        if white_ratio > effective_white_limit:
            hint = (
                "Provide an explicit bbox around the prescription block, or confirm the page "
                "has visible content."
            )
            if text_chars < 20:
                hint = (
                    "Page has little or no extractable text — verify page number and PDF path "
                    f"({rel_source})."
                )
            sidecar["warning"] = (
                f"white_ratio {white_ratio:.2f} exceeds limit {effective_white_limit:.2f}; "
                "image looks like a full-page dump — provide a tighter bbox or verify content."
            )
            return {
                "ok": False,
                "error": "too_much_whitespace",
                "white_ratio": round(white_ratio, 4),
                "max_white_ratio": effective_white_limit,
                "warning": sidecar["warning"],
                "hint": hint,
                "png_path": rel_png,
                "sidecar_path": rel_sidecar,
                **sidecar,
            }

        image.save(png_path, format="PNG", optimize=True)
        sidecar_path.write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return {
            "ok": True,
            "png_path": rel_png,
            "sidecar_path": rel_sidecar,
            "slug": slug,
            **sidecar,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "crop_failed",
            "message": str(exc),
        }
    finally:
        doc.close()
