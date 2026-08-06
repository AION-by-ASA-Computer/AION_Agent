"""Deterministic coverage for src.tools.doc_ingest (no LLM, no MCP, no OCR service).

The regression these tests protect against is the one seen in production: a
200-page decree that could not be extracted, and a concatenated text file that
grep silently skips once it grows past AION_GREP_MAX_FILE_BYTES.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tools.doc_ingest import ingest_document, slugify_document_name

PAGE_COUNT = 200
# Sentinel reproducing the real task: a numbered prescription on a known page.
PRESCRIPTION_PAGE = 101
PRESCRIPTION_TEXT = "[53] Il Gestore e tenuto al rispetto dei valori limite di rumore"
BLANK_PAGES = {7, 42}


_FILLER = (
    "Commissione Istruttoria IPPC - Centrale termoelettrica - testo di riempimento "
    "per riprodurre la densita tipica di una pagina di decreto autorizzativo."
)


def _build_pdf(path: Path, pages: int = PAGE_COUNT) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for page_no in range(1, pages + 1):
        if page_no not in BLANK_PAGES:
            c.drawString(72, 780, f"PAGINA {page_no} marcatore acustico")
            # Real pages carry hundreds of characters; a sparse fixture would
            # trip the missing-text-layer heuristic for the wrong reason.
            for row, offset in enumerate(range(750, 690, -15)):
                c.drawString(72, offset, f"{_FILLER} riga {row}")
            if page_no == PRESCRIPTION_PAGE:
                c.drawString(72, 660, PRESCRIPTION_TEXT)
        c.showPage()
    c.save()
    return path


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("docsrc")
    return _build_pdf(root / "08b3392800_DECRETOCOMPLETO.pdf")


@pytest.fixture()
def session_root(tmp_path) -> Path:
    return tmp_path


def _pages_dir(session_root: Path, slug: str) -> Path:
    return session_root / "derived" / "docs" / slug / "pages"


def test_slugify_strips_upload_prefix():
    assert slugify_document_name("08b3392800_DECRETOCOMPLETO.pdf") == "decretocompleto"
    assert slugify_document_name("esempio per ai.pdf") == "esempio_per_ai"
    assert slugify_document_name("___.pdf") == "document"


@pytest.mark.asyncio
async def test_writes_one_file_per_page(sample_pdf, session_root):
    manifest = await ingest_document(sample_pdf, session_root, budget_sec=600)

    assert manifest["ok"] is True
    assert manifest["partial"] is False
    assert manifest["pages_total"] == PAGE_COUNT
    assert manifest["pages_written"] == PAGE_COUNT

    pages = sorted(_pages_dir(session_root, manifest["slug"]).glob("p*.txt"))
    assert len(pages) == PAGE_COUNT
    assert pages[0].name == "p0001.txt"
    assert pages[-1].name == "p0200.txt"

    target = _pages_dir(session_root, manifest["slug"]) / "p0101.txt"
    assert "[53]" in target.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_manifest_is_persisted_and_small(sample_pdf, session_root):
    manifest = await ingest_document(sample_pdf, session_root, budget_sec=600)

    on_disk = (
        session_root / "derived" / "docs" / manifest["slug"] / "manifest.json"
    ).read_text(encoding="utf-8")
    assert json.loads(on_disk)["slug"] == manifest["slug"]
    # Must stay well under the tool-offload threshold (8000 chars) so the model
    # sees the manifest inline instead of a pointer to a file.
    assert len(json.dumps(manifest, ensure_ascii=False)) < 4000


@pytest.mark.asyncio
async def test_page_files_stay_greppable(sample_pdf, session_root):
    """Every page must sit below the grep size cap that silently skips files."""
    from src.tools.session_fs_tools import _grep_max_file_bytes, grep_content

    manifest = await ingest_document(sample_pdf, session_root, budget_sec=600)
    pages_dir = _pages_dir(session_root, manifest["slug"])

    cap = _grep_max_file_bytes()
    assert all(p.stat().st_size < cap for p in pages_dir.glob("p*.txt"))

    hits = grep_content(
        session_root,
        session_root / "derived",
        "marcatore acustico",
        glob_filter=f"docs/{manifest['slug']}/pages/*.txt",
        max_matches=PAGE_COUNT + 10,
    )
    assert len(hits) == PAGE_COUNT - len(BLANK_PAGES)


@pytest.mark.asyncio
async def test_grep_hit_filename_carries_page_number(sample_pdf, session_root):
    from src.tools.session_fs_tools import grep_content

    manifest = await ingest_document(sample_pdf, session_root, budget_sec=600)
    hits = grep_content(
        session_root,
        session_root / "derived",
        r"\[53\]",
        glob_filter=f"docs/{manifest['slug']}/pages/*.txt",
    )
    assert len(hits) == 1
    assert hits[0]["file"].endswith(f"p{PRESCRIPTION_PAGE:04d}.txt")


@pytest.mark.asyncio
async def test_partial_run_reports_resume_point(sample_pdf, session_root):
    ticks = iter(range(0, 10_000))
    manifest = await ingest_document(
        sample_pdf, session_root, budget_sec=5, clock=lambda: float(next(ticks))
    )

    assert manifest["partial"] is True
    assert manifest["resume_from"] == 5
    assert manifest["pages_written"] == 4
    assert "doc_ingest again with first_page=5" in manifest["next_step"]


@pytest.mark.asyncio
async def test_second_call_resumes_and_skips_existing(sample_pdf, session_root):
    ticks = iter(range(0, 10_000))
    first = await ingest_document(
        sample_pdf, session_root, budget_sec=5, clock=lambda: float(next(ticks))
    )
    assert first["partial"] is True

    second = await ingest_document(sample_pdf, session_root, budget_sec=600)

    assert second["partial"] is False
    assert second["pages_skipped_existing"] == first["pages_written"]
    assert second["pages_written"] == PAGE_COUNT - first["pages_written"]
    assert len(list(_pages_dir(session_root, second["slug"]).glob("p*.txt"))) == PAGE_COUNT


@pytest.mark.asyncio
async def test_ocr_runs_only_on_pages_without_text_layer(sample_pdf, session_root):
    seen: list[int] = []

    async def fake_ocr(page_no: int, image_bytes: bytes, mime: str) -> str:
        seen.append(page_no)
        assert image_bytes[:4] == b"\x89PNG"
        assert mime == "image/png"
        return f"OCR PAGINA {page_no}"

    manifest = await ingest_document(
        sample_pdf, session_root, budget_sec=600, ocr_page=fake_ocr
    )

    assert sorted(seen) == sorted(BLANK_PAGES)
    assert manifest["ocr_pages"] == len(BLANK_PAGES)
    assert manifest["text_layer_pages"] == PAGE_COUNT - len(BLANK_PAGES)
    assert manifest["empty_pages"] == []

    recovered = _pages_dir(session_root, manifest["slug"]) / "p0007.txt"
    assert recovered.read_text(encoding="utf-8") == "OCR PAGINA 7"


@pytest.mark.asyncio
async def test_min_text_chars_controls_the_ocr_trigger(sample_pdf, session_root):
    """A page is sent to OCR only when its text layer is below the threshold."""
    seen: list[int] = []

    async def fake_ocr(page_no: int, image_bytes: bytes, mime: str) -> str:
        seen.append(page_no)
        return f"OCR PAGINA {page_no}"

    await ingest_document(
        sample_pdf,
        session_root,
        budget_sec=600,
        last_page=5,
        ocr_page=fake_ocr,
        min_text_chars=10_000,
    )
    assert seen == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_ocr_mode_always_bypasses_the_text_layer(sample_pdf, session_root):
    seen: list[int] = []

    async def fake_ocr(page_no: int, image_bytes: bytes, mime: str) -> str:
        seen.append(page_no)
        return f"OCR PAGINA {page_no}"

    manifest = await ingest_document(
        sample_pdf,
        session_root,
        budget_sec=600,
        last_page=3,
        ocr_mode="always",
        ocr_page=fake_ocr,
    )

    assert seen == [1, 2, 3]
    assert manifest["ocr_pages"] == 3
    assert manifest["text_layer_pages"] == 0


@pytest.mark.asyncio
async def test_ocr_failure_keeps_the_text_layer(sample_pdf, session_root):
    async def failing_ocr(page_no, image_bytes, mime):
        raise RuntimeError("OCR service unreachable")

    manifest = await ingest_document(
        sample_pdf, session_root, budget_sec=600, ocr_page=failing_ocr
    )

    # Pages with text are untouched; the blank ones are reported as failed rather
    # than silently counted as successfully extracted.
    assert manifest["ocr_pages"] == 0
    assert manifest["text_layer_pages"] == PAGE_COUNT - len(BLANK_PAGES)
    assert manifest["ocr_failed_pages"] == sorted(BLANK_PAGES)
    assert manifest["ocr_failed_pages_count"] == len(BLANK_PAGES)
    blank = _pages_dir(session_root, manifest["slug"]) / "p0007.txt"
    assert "OCR failed for page 7" in blank.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_ocr_mode_never_reports_empty_pages(sample_pdf, session_root):
    async def unexpected_ocr(page_no, image_bytes, mime):  # pragma: no cover
        raise AssertionError("OCR must not run with ocr_mode='never'")

    manifest = await ingest_document(
        sample_pdf,
        session_root,
        budget_sec=600,
        ocr_mode="never",
        ocr_page=unexpected_ocr,
    )

    assert manifest["ocr_pages"] == 0
    assert manifest["empty_pages"] == sorted(BLANK_PAGES)
    assert manifest["empty_pages_count"] == len(BLANK_PAGES)


@pytest.mark.asyncio
async def test_full_text_is_opt_in(sample_pdf, session_root):
    default = await ingest_document(sample_pdf, session_root, budget_sec=600)
    root = session_root / "derived" / "docs" / default["slug"]
    assert not (root / "full.txt").exists()
    assert default["full_text"] is None

    with_full = await ingest_document(
        sample_pdf, session_root, budget_sec=600, write_full=True
    )
    full = root / "full.txt"
    assert full.exists()
    assert with_full["full_text"].endswith("full.txt")
    body = full.read_text(encoding="utf-8")
    assert "=== PAGE 101 ===" in body
    assert "[53]" in body


@pytest.mark.asyncio
async def test_force_reextracts_pages(sample_pdf, session_root):
    manifest = await ingest_document(sample_pdf, session_root, budget_sec=600)
    stale = _pages_dir(session_root, manifest["slug"]) / "p0101.txt"
    stale.write_text("contenuto obsoleto", encoding="utf-8")

    refreshed = await ingest_document(
        sample_pdf, session_root, budget_sec=600, last_page=PRESCRIPTION_PAGE, force=True
    )

    assert refreshed["pages_skipped_existing"] == 0
    assert "[53]" in stale.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_page_range_limits_extraction(sample_pdf, session_root):
    manifest = await ingest_document(
        sample_pdf, session_root, budget_sec=600, first_page=10, last_page=12
    )

    assert manifest["range"] == [10, 12]
    assert manifest["pages_written"] == 3
    names = sorted(p.name for p in _pages_dir(session_root, manifest["slug"]).glob("*.txt"))
    assert names == ["p0010.txt", "p0011.txt", "p0012.txt"]


@pytest.mark.asyncio
async def test_first_page_excerpt_supports_identity_check(sample_pdf, session_root):
    manifest = await ingest_document(sample_pdf, session_root, budget_sec=600)
    assert "PAGINA 1" in manifest["first_page_excerpt"]


@pytest.mark.asyncio
async def test_invalid_inputs_return_structured_errors(sample_pdf, session_root, tmp_path):
    bad_mode = await ingest_document(sample_pdf, session_root, ocr_mode="sometimes")
    assert bad_mode == {
        "ok": False,
        "error": "invalid_ocr_mode",
        "message": "ocr_mode must be auto|never|always, got 'sometimes'",
    }

    missing = await ingest_document(tmp_path / "nope.pdf", session_root)
    assert missing["error"] == "not_a_file"

    out_of_range = await ingest_document(
        sample_pdf, session_root, first_page=PAGE_COUNT + 5, budget_sec=600
    )
    assert out_of_range["error"] == "empty_range"
