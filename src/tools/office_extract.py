"""
Extract structured text, image references, and page-mapped content from Word (.docx/.doc) documents.

Enables high-efficiency document review without context exhaustion:
- Extracts text hierarchy (headings, paragraphs, tables, footnotes).
- Extracts and maps embedded images with contextual references (captions, parent section, docPr metadata).
- Saves full clean text to derived/extracted_text/<doc_stem>_full.txt (ready for sandbox_grep_content).
- Optionally converts to PDF for exact page-number mapping.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.session_workspace import safe_resolve, session_root
from src.tools.office_convert import (
    convert_legacy_word_sync,
    find_soffice,
    is_legacy_word_upload,
)

logger = logging.getLogger("aion.office_extract")

_NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "v": "urn:schemas-microsoft-com:vml",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
}

_EXTRACTED_TEXT_DIR = "derived/extracted_text"
_EXTRACTED_IMAGES_DIR = "derived/extracted_images"
_CONVERTED_DIR = "derived/converted"


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem or "document"
    stem = re.sub(r"[^\w.\-]+", "_", stem).strip("._")
    return stem or "document"


def _extract_text_from_node(node: ET.Element) -> str:
    """Extract plain text runs from XML node, handling whitespace & line breaks."""
    texts: List[str] = []
    for elem in node.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "t" and elem.text:
            texts.append(elem.text)
        elif tag == "tab":
            texts.append("\t")
        elif tag in ("br", "cr"):
            texts.append("\n")
    return "".join(texts).strip()


def _get_relationships(zf: zipfile.ZipFile, rels_path: str = "word/_rels/document.xml.rels") -> Dict[str, str]:
    """Map relationship ID (rIdX) -> Target filename inside zip."""
    rels: Dict[str, str] = {}
    if rels_path not in zf.namelist():
        return rels
    try:
        data = zf.read(rels_path)
        root = ET.fromstring(data)
        for child in root:
            rid = child.attrib.get("Id")
            target = child.attrib.get("Target")
            if rid and target:
                if target.startswith("/"):
                    target = target.lstrip("/")
                elif not target.startswith("word/"):
                    target = f"word/{target}"
                rels[rid] = target
    except Exception as e:
        logger.warning("Failed to parse rels %s: %s", rels_path, e)
    return rels


def _find_drawings_in_node(node: ET.Element, rels: Dict[str, str]) -> List[Dict[str, Any]]:
    """Inspect XML node for drawings/pictures and return metadata + target media."""
    found: List[Dict[str, Any]] = []

    # 1. DrawingML: wp:docPr and a:blip
    for drawing in node.findall(".//w:drawing", _NAMESPACES):
        doc_pr = drawing.find(".//wp:docPr", _NAMESPACES)
        name = doc_pr.attrib.get("name", "") if doc_pr is not None else ""
        title = doc_pr.attrib.get("title", "") if doc_pr is not None else ""
        descr = doc_pr.attrib.get("descr", "") if doc_pr is not None else ""
        doc_id = doc_pr.attrib.get("id", "") if doc_pr is not None else ""

        # blip
        for blip in drawing.findall(".//a:blip", _NAMESPACES):
            embed_id = blip.attrib.get(f"{{{_NAMESPACES['r']}}}embed") or blip.attrib.get("r:embed")
            if embed_id and embed_id in rels:
                found.append(
                    {
                        "rel_id": embed_id,
                        "zip_target": rels[embed_id],
                        "doc_prop_id": doc_id,
                        "doc_prop_name": name,
                        "doc_prop_title": title,
                        "doc_prop_descr": descr,
                    }
                )

    # 2. VML shapes: v:imagedata
    for v_img in node.findall(".//v:imagedata", _NAMESPACES):
        rid = (
            v_img.attrib.get(f"{{{_NAMESPACES['r']}}}id")
            or v_img.attrib.get("r:id")
            or v_img.attrib.get(f"{{{_NAMESPACES['r']}}}href")
        )
        title = v_img.attrib.get("title", "")
        if rid and rid in rels:
            found.append(
                {
                    "rel_id": rid,
                    "zip_target": rels[rid],
                    "doc_prop_id": "",
                    "doc_prop_name": "",
                    "doc_prop_title": title,
                    "doc_prop_descr": "",
                }
            )

    return found


def _is_heading(p_node: ET.Element) -> Tuple[bool, int]:
    """Determine if a paragraph is a heading and its level (1-6)."""
    p_style = p_node.find(".//w:pPr/w:pStyle", _NAMESPACES)
    if p_style is not None:
        val = p_style.attrib.get(f"{{{_NAMESPACES['w']}}}val") or p_style.attrib.get("w:val", "")
        val_lower = val.lower()
        if "heading" in val_lower or "titolo" in val_lower:
            digits = re.findall(r"\d+", val)
            level = int(digits[0]) if digits else 1
            return True, min(6, max(1, level))
        if "toc" in val_lower or "sommario" in val_lower or "indice" in val_lower:
            return True, 1

    # Check outline level if defined
    outline = p_node.find(".//w:pPr/w:outlineLvl", _NAMESPACES)
    if outline is not None:
        val = outline.attrib.get(f"{{{_NAMESPACES['w']}}}val") or outline.attrib.get("w:val", "0")
        try:
            return True, int(val) + 1
        except ValueError:
            pass

    return False, 0


def _extract_pages_from_pdf(pdf_path: Path) -> List[Dict[str, Any]]:
    """Extract page-by-page text from PDF using available python libraries or fallback."""
    pages: List[Dict[str, Any]] = []

    # 1. Try PyMuPDF (fitz)
    try:
        import fitz  # noqa: F401

        doc = fitz.open(str(pdf_path))
        for pno in range(len(doc)):
            page = doc[pno]
            txt = page.get_text("text") or ""
            pages.append(
                {
                    "page_number": pno + 1,
                    "text": txt.strip(),
                    "char_count": len(txt),
                }
            )
        return pages
    except ImportError:
        pass
    except Exception as e:
        logger.warning("fitz extract failed on %s: %s", pdf_path.name, e)

    # 2. Try pypdf
    try:
        import pypdf

        reader = pypdf.PdfReader(str(pdf_path))
        for pno, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            pages.append(
                {
                    "page_number": pno + 1,
                    "text": txt.strip(),
                    "char_count": len(txt),
                }
            )
        return pages
    except ImportError:
        pass
    except Exception as e:
        logger.warning("pypdf extract failed on %s: %s", pdf_path.name, e)

    # 3. Try pdftotext CLI tool if present
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            cmd = [pdftotext, "-layout", str(pdf_path), str(tmp_path)]
            subprocess.run(cmd, capture_output=True, check=False, timeout=30)
            if tmp_path.is_file():
                raw = tmp_path.read_text(encoding="utf-8", errors="replace")
                # pdftotext separates pages with \x0c form feed
                raw_pages = raw.split("\x0c")
                for pno, ptext in enumerate(raw_pages[:-1] if raw.endswith("\x0c") else raw_pages):
                    pages.append(
                        {
                            "page_number": pno + 1,
                            "text": ptext.strip(),
                            "char_count": len(ptext),
                        }
                    )
                return pages
        except Exception as e:
            logger.warning("pdftotext CLI failed: %s", e)
        finally:
            if tmp_path.is_file():
                tmp_path.unlink()

    return pages


def extract_docx_content(
    session_id: str,
    relative_path: str,
    *,
    extract_images: bool = True,
    convert_pdf_pages: bool = False,
    max_chars_summary: int = 1500,
) -> Dict[str, Any]:
    """
    Extract structured text, image references with captions, and optional page-mapped PDF.

    Saves full text in derived/extracted_text/<stem>_full.txt.
    Returns a compact summary for the agent.
    """
    rel = (relative_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        return {"ok": False, "error": "relative_path_empty", "message": "Path vuoto."}

    # Resolve source path
    src = safe_resolve(session_id, rel, must_exist=True)
    filename = src.name

    # Handle legacy .doc automatically
    docx_path = src
    is_legacy = filename.lower().endswith((".doc", ".dot", ".wps")) and not filename.lower().endswith((".docx", ".dotx"))
    if is_legacy:
        # Check if already converted
        stem = _safe_stem(filename)
        candidate = session_root(session_id) / _CONVERTED_DIR / f"{stem}.docx"
        if candidate.is_file():
            docx_path = candidate
        else:
            meta = {
                "relative_path": rel,
                "original_name": filename,
                "mime": "application/msword",
            }
            conv_res = convert_legacy_word_sync(session_id, meta)
            if conv_res.get("conversion_status") == "ok":
                docx_path = safe_resolve(session_id, conv_res["converted_docx_path"], must_exist=True)
            else:
                return {
                    "ok": False,
                    "error": "conversion_failed",
                    "message": f"Impossibile convertire il file legacy .doc in .docx: {conv_res.get('conversion_error')}",
                }

    if not zipfile.is_zipfile(docx_path):
        return {
            "ok": False,
            "error": "not_a_docx",
            "message": f"Il file {docx_path.name} non è un archivio Word OpenXML .docx valido.",
        }

    stem = _safe_stem(docx_path.name)
    sroot = session_root(session_id)

    text_out_dir = sroot / _EXTRACTED_TEXT_DIR
    text_out_dir.mkdir(parents=True, exist_ok=True)

    img_out_dir = sroot / _EXTRACTED_IMAGES_DIR / stem
    if extract_images:
        img_out_dir.mkdir(parents=True, exist_ok=True)

    # Parse DOCX zip contents
    paragraphs_data: List[Dict[str, Any]] = []
    tables_data: List[Dict[str, Any]] = []
    images_catalog: List[Dict[str, Any]] = []
    full_text_lines: List[str] = []
    heading_outline: List[Dict[str, Any]] = []

    current_headings: List[str] = []

    with zipfile.ZipFile(docx_path, "r") as zf:
        rels = _get_relationships(zf, "word/_rels/document.xml.rels")

        if "word/document.xml" not in zf.namelist():
            return {
                "ok": False,
                "error": "missing_document_xml",
                "message": "word/document.xml non trovato all'interno del docx.",
            }

        doc_xml = zf.read("word/document.xml")
        root = ET.fromstring(doc_xml)
        body = root.find("w:body", _NAMESPACES)
        if body is None:
            body = root

        # Scan all children in body (paragraphs and tables)
        body_elements = list(body)
        total_elements = len(body_elements)

        # Pre-extract text from all paragraphs to easily lookup adjacent captions
        p_texts: Dict[int, str] = {}
        for idx, elem in enumerate(body_elements):
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "p":
                p_texts[idx] = _extract_text_from_node(elem)

        def _get_adjacent_caption(el_idx: int) -> str:
            """Search nearby paragraphs (current, next, previous) for figure captions."""
            caption_patterns = [
                re.compile(r"^(?:figura|fig\.|fig|immagine|grafico|stralcio|tabella|schema|planimetria)\b", re.IGNORECASE),
                re.compile(r"(?:figura|immagine|grafico|stralcio|tabella)\s+\d+", re.IGNORECASE),
            ]
            # Check current paragraph
            curr = p_texts.get(el_idx, "")
            for pat in caption_patterns:
                if pat.search(curr):
                    return curr.strip()

            # Check next paragraph (common: image then caption below)
            nxt = p_texts.get(el_idx + 1, "")
            for pat in caption_patterns:
                if pat.search(nxt):
                    return nxt.strip()

            # Check previous paragraph (common: caption above image)
            prev = p_texts.get(el_idx - 1, "")
            for pat in caption_patterns:
                if pat.search(prev):
                    return prev.strip()

            # Fallback: if next paragraph is short, take it as description
            if nxt and len(nxt) < 120:
                return nxt.strip()
            if prev and len(prev) < 120:
                return prev.strip()
            return ""

        par_counter = 0
        tbl_counter = 0
        img_counter = 0

        for el_idx, elem in enumerate(body_elements):
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            if tag == "p":
                par_counter += 1
                text = p_texts.get(el_idx, "")
                is_head, head_lvl = _is_heading(elem)

                if is_head and text:
                    # Update hierarchy
                    if head_lvl <= len(current_headings):
                        current_headings = current_headings[: head_lvl - 1]
                    current_headings.append(text)
                    heading_outline.append({"level": head_lvl, "title": text, "par_index": par_counter})
                    full_text_lines.append(f"\n{'#' * head_lvl} {text}\n")
                elif text:
                    full_text_lines.append(text)

                # Check for track changes in paragraph
                ins_nodes = elem.findall(".//w:ins", _NAMESPACES)
                del_nodes = elem.findall(".//w:del", _NAMESPACES)
                has_revisions = bool(ins_nodes or del_nodes)

                paragraphs_data.append(
                    {
                        "par_index": par_counter,
                        "heading_path": list(current_headings),
                        "text": text,
                        "is_heading": is_head,
                        "heading_level": head_lvl,
                        "has_revisions": has_revisions,
                    }
                )

                # Check for drawings / images
                drawings = _find_drawings_in_node(elem, rels)
                for d in drawings:
                    img_counter += 1
                    ztarget = d["zip_target"]
                    orig_img_name = Path(ztarget).name
                    saved_rel = ""

                    if extract_images and ztarget in zf.namelist():
                        img_bytes = zf.read(ztarget)
                        target_filename = f"img_{img_counter:02d}_{orig_img_name}"
                        out_img_path = img_out_dir / target_filename
                        out_img_path.write_bytes(img_bytes)
                        saved_rel = str(out_img_path.relative_to(sroot)).replace("\\", "/")
                        size_b = len(img_bytes)
                    else:
                        size_b = 0

                    caption = _get_adjacent_caption(el_idx)
                    active_heading = current_headings[-1] if current_headings else "Introduzione / Generale"

                    images_catalog.append(
                        {
                            "image_index": img_counter,
                            "media_filename": orig_img_name,
                            "saved_relative_path": saved_rel,
                            "heading_context": active_heading,
                            "caption_or_adjacent_text": caption,
                            "doc_prop_name": d["doc_prop_name"],
                            "doc_prop_title": d["doc_prop_title"],
                            "par_index": par_counter,
                            "size_bytes": size_b,
                        }
                    )

            elif tag == "tbl":
                tbl_counter += 1
                tbl_rows: List[List[str]] = []
                full_text_lines.append(f"\n[TABELLA #{tbl_counter}]")

                for tr in elem.findall(".//w:tr", _NAMESPACES):
                    row_cells: List[str] = []
                    for tc in tr.findall(".//w:tc", _NAMESPACES):
                        cell_text = _extract_text_from_node(tc)
                        row_cells.append(cell_text)
                    if row_cells:
                        tbl_rows.append(row_cells)
                        full_text_lines.append(" | ".join(row_cells))

                full_text_lines.append(f"[/TABELLA #{tbl_counter}]\n")

                active_heading = current_headings[-1] if current_headings else "Documento"
                tables_data.append(
                    {
                        "table_index": tbl_counter,
                        "heading_context": active_heading,
                        "rows_count": len(tbl_rows),
                        "cols_count": len(tbl_rows[0]) if tbl_rows else 0,
                        "rows": tbl_rows,
                    }
                )

                # Check if table cells contain images
                for tc in elem.findall(".//w:tc", _NAMESPACES):
                    drawings = _find_drawings_in_node(tc, rels)
                    for d in drawings:
                        img_counter += 1
                        ztarget = d["zip_target"]
                        orig_img_name = Path(ztarget).name
                        saved_rel = ""
                        if extract_images and ztarget in zf.namelist():
                            img_bytes = zf.read(ztarget)
                            target_filename = f"img_{img_counter:02d}_{orig_img_name}"
                            out_img_path = img_out_dir / target_filename
                            out_img_path.write_bytes(img_bytes)
                            saved_rel = str(out_img_path.relative_to(sroot)).replace("\\", "/")
                            size_b = len(img_bytes)
                        else:
                            size_b = 0

                        images_catalog.append(
                            {
                                "image_index": img_counter,
                                "media_filename": orig_img_name,
                                "saved_relative_path": saved_rel,
                                "heading_context": f"{active_heading} (Tabella #{tbl_counter})",
                                "caption_or_adjacent_text": f"Immagine all'interno della Tabella #{tbl_counter}",
                                "doc_prop_name": d["doc_prop_name"],
                                "doc_prop_title": d["doc_prop_title"],
                                "par_index": par_counter,
                                "size_bytes": size_b,
                            }
                        )

    # Save full clean text file for grep
    full_text_content = "\n".join(full_text_lines)
    full_text_path = text_out_dir / f"{stem}_full.txt"
    full_text_path.write_text(full_text_content, encoding="utf-8")
    full_text_rel = str(full_text_path.relative_to(sroot)).replace("\\", "/")

    # Save structured JSON
    struct_data = {
        "source_document": filename,
        "docx_path": str(docx_path.relative_to(sroot)).replace("\\", "/"),
        "total_paragraphs": len(paragraphs_data),
        "total_tables": len(tables_data),
        "total_images": len(images_catalog),
        "outline": heading_outline,
        "images": images_catalog,
        "tables": tables_data,
        "paragraphs": paragraphs_data,
    }
    struct_path = text_out_dir / f"{stem}_structure.json"
    struct_path.write_text(json.dumps(struct_data, ensure_ascii=False, indent=2), encoding="utf-8")
    struct_rel = str(struct_path.relative_to(sroot)).replace("\\", "/")

    # Handle PDF page conversion if requested
    pdf_pages_rel = None
    pdf_pages_count = 0
    if convert_pdf_pages:
        soffice = find_soffice()
        if soffice:
            conv_pdf_dir = sroot / _CONVERTED_DIR
            conv_pdf_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                soffice,
                "--headless",
                "--norestore",
                "--invisible",
                "--convert-to",
                "pdf",
                "--outdir",
                str(conv_pdf_dir),
                str(docx_path),
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=60, check=False)
                pdf_target = conv_pdf_dir / f"{stem}.pdf"
                if pdf_target.is_file():
                    pages = _extract_pages_from_pdf(pdf_target)
                    pdf_pages_count = len(pages)
                    pages_out_path = text_out_dir / f"{stem}_pages.json"
                    pages_out_path.write_text(
                        json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    pdf_pages_rel = str(pages_out_path.relative_to(sroot)).replace("\\", "/")
            except Exception as e:
                logger.warning("PDF conversion for pages failed: %s", e)

    # Prepare head summary for the LLM
    preview = full_text_content[:max_chars_summary]
    if len(full_text_content) > max_chars_summary:
        preview += f"\n... [Troncato: il documento completo ({len(full_text_content)} caratteri) è salvato in {full_text_rel}]"

    return {
        "ok": True,
        "source_document": filename,
        "stats": {
            "total_characters": len(full_text_content),
            "total_paragraphs": len(paragraphs_data),
            "total_tables": len(tables_data),
            "total_images_extracted": len(images_catalog),
            "pdf_pages_count": pdf_pages_count,
        },
        "artifacts": {
            "full_text_file": full_text_rel,
            "structure_json": struct_rel,
            "pdf_pages_json": pdf_pages_rel,
        },
        "outline": heading_outline,
        "images_catalog": images_catalog,
        "search_instructions": (
            f"Per documenti grandi o ricerche mirate, usa `sandbox_grep_content(relative_root='derived', pattern='...')` "
            f"sul file `{full_text_rel}` senza intasare il contesto. "
            f"Tutte le {len(images_catalog)} immagini sono salvate con didascalia e capitolo di appartenenza in `images_catalog`."
        ),
        "text_preview": preview,
    }
