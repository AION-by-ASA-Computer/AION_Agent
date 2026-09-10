"""Test parallel OCR execution, concurrency, and deterministic page ordering in doc_ingest."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from src.tools.doc_ingest import ingest_document

PAGE_COUNT = 30
BLANK_PAGES = set(range(1, PAGE_COUNT + 1))  # All scanned / blank pages for OCR


def _build_scanned_pdf(path: Path, pages: int = PAGE_COUNT) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for _ in range(pages):
        # Empty pages (no text layer) to trigger OCR on every page
        c.showPage()
    c.save()
    return path


@pytest.fixture(scope="module")
def scanned_pdf(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("docsrc_scanned")
    return _build_scanned_pdf(root / "scanned_doc.pdf")


@pytest.fixture()
def session_root(tmp_path) -> Path:
    return tmp_path


def _pages_dir(session_root: Path, slug: str) -> Path:
    return session_root / "derived" / "docs" / slug / "pages"


@pytest.mark.anyio
async def test_parallel_ocr_order_and_concurrency(scanned_pdf, session_root, monkeypatch):
    """Verify that parallel OCR tasks complete concurrently and preserve exact page ordering."""
    active_concurrency = 0
    max_concurrency_seen = 0
    concurrency_lock = asyncio.Lock()
    call_order: list[int] = []

    async def mock_parallel_ocr(page_no: int, image_bytes: bytes, mime: str) -> str:
        nonlocal active_concurrency, max_concurrency_seen
        async with concurrency_lock:
            active_concurrency += 1
            if active_concurrency > max_concurrency_seen:
                max_concurrency_seen = active_concurrency
            call_order.append(page_no)

        # Introduce variable async delay (e.g. later pages finish earlier)
        # to test that completion order does NOT mess up final file numbering or content
        delay = 0.05 if page_no % 2 == 0 else 0.01
        await asyncio.sleep(delay)

        async with concurrency_lock:
            active_concurrency -= 1

        return f"CONTENUTO OCR PAGINA {page_no:04d} - DATO_CHIAVE_{page_no}"

    monkeypatch.setenv("AION_DOC_INGEST_CONCURRENCY", "6")

    manifest = await ingest_document(
        scanned_pdf,
        session_root,
        budget_sec=60,
        ocr_mode="auto",
        ocr_page=mock_parallel_ocr,
        write_full=True,
    )

    assert manifest["ok"] is True
    assert manifest["partial"] is False
    assert manifest["pages_total"] == PAGE_COUNT
    assert manifest["pages_written"] == PAGE_COUNT
    assert manifest["ocr_pages"] == PAGE_COUNT

    # Concurrency was observed
    assert max_concurrency_seen > 1

    # Check each individual page file
    pages_dir = _pages_dir(session_root, manifest["slug"])
    for p in range(1, PAGE_COUNT + 1):
        page_file = pages_dir / f"p{p:04d}.txt"
        assert page_file.exists(), f"Missing page file p{p:04d}.txt"
        content = page_file.read_text(encoding="utf-8")
        assert f"CONTENUTO OCR PAGINA {p:04d}" in content
        assert f"DATO_CHIAVE_{p}" in content

    # Check that full.txt has pages in exact sequential order
    full_path = session_root / "derived" / "docs" / manifest["slug"] / "full.txt"
    assert full_path.exists()
    full_content = full_path.read_text(encoding="utf-8")

    last_index = -1
    for p in range(1, PAGE_COUNT + 1):
        marker = f"=== PAGE {p} ==="
        idx = full_content.find(marker)
        assert idx != -1, f"Marker {marker} not found in full.txt"
        assert idx > last_index, f"Page {p} out of order in full.txt"
        last_index = idx


@pytest.mark.anyio
async def test_parallel_ocr_partial_timeout_resumption(scanned_pdf, session_root):
    """Verify that if budget expires during parallel execution, completed pages are preserved and resumption works."""
    cur_time = 0.0

    def simulated_clock() -> float:
        nonlocal cur_time
        cur_time += 1.0
        return cur_time

    async def mock_ocr(page_no: int, image_bytes: bytes, mime: str) -> str:
        return f"PAGE_{page_no}_TEXT"

    # With budget_sec=10 and clock advancing by 1 per call, only first batch should complete
    first_manifest = await ingest_document(
        scanned_pdf,
        session_root,
        budget_sec=10,
        ocr_mode="auto",
        ocr_page=mock_ocr,
        clock=simulated_clock,
    )

    assert first_manifest["ok"] is True
    assert first_manifest["partial"] is True
    assert first_manifest["resume_from"] > 1
    resume_from = first_manifest["resume_from"]

    # Resume without budget constraint to finish
    second_manifest = await ingest_document(
        scanned_pdf,
        session_root,
        first_page=resume_from,
        budget_sec=60,
        ocr_mode="auto",
        ocr_page=mock_ocr,
    )

    assert second_manifest["ok"] is True
    assert second_manifest["partial"] is False
    assert second_manifest["pages_written"] + first_manifest["pages_written"] == PAGE_COUNT
