"""Unit tests for pdf_evidence crop tool."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from src.benchmarks.long_document.synthetic import build_rumore_decreto_pdf
from src.tools.pdf_evidence import (
    auto_trim_image,
    compute_white_ratio,
    max_white_ratio,
    pdf_evidence_crop_sync,
)


def test_compute_white_ratio_all_white():
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    assert compute_white_ratio(img) == pytest.approx(1.0)


def test_compute_white_ratio_mixed():
    img = Image.new("RGB", (10, 10), color=(255, 255, 255))
    for x in range(5):
        for y in range(10):
            img.putpixel((x, y), (0, 0, 0))
    assert compute_white_ratio(img) == pytest.approx(0.5)


def test_auto_trim_crops_whitespace():
    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    for x in range(40, 80):
        for y in range(50, 90):
            img.putpixel((x, y), (10, 10, 10))
    trimmed = auto_trim_image(img, padding=2)
    assert trimmed.width < img.width
    assert trimmed.height < img.height
    assert compute_white_ratio(trimmed) < 0.95


def test_pdf_evidence_crop_writes_png_and_sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_PDF_EVIDENCE_MAX_WHITE_RATIO", "0.99")
    pdf = build_rumore_decreto_pdf(
        tmp_path / "decreto.pdf", pages=5, prescription_page=3, pmc_page=4
    )
    session = tmp_path / "session"
    session.mkdir()

    out = pdf_evidence_crop_sync(
        pdf,
        session,
        page=3,
        caption="decreto / §8.9 / pag. 3",
        source_relative_path="uploads/decreto.pdf",
    )
    assert out["ok"] is True
    assert out["page"] == 3
    assert out["caption"] == "decreto / §8.9 / pag. 3"
    assert out["cropped"] is True
    assert out["crop_method"] in {"text_blocks", "auto_trim"}
    assert out["white_ratio"] < 0.99

    png = session / out["png_path"]
    sidecar = session / out["sidecar_path"]
    assert png.is_file()
    assert sidecar.is_file()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["page"] == 3
    assert meta["png_path"] == out["png_path"]


def test_pdf_evidence_crop_rejects_whitespace_heavy_full_page(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_PDF_EVIDENCE_MAX_WHITE_RATIO", "0.90")
    pdf = build_rumore_decreto_pdf(
        tmp_path / "sparse.pdf",
        pages=1,
        prescription_page=99,
        pmc_page=99,
        blank_pages=frozenset({1}),
    )
    session = tmp_path / "session"
    session.mkdir()

    out = pdf_evidence_crop_sync(
        pdf,
        session,
        page=1,
        full_page=True,
        caption="full page test",
    )
    assert out["ok"] is False
    assert out["error"] == "too_much_whitespace"
    assert out["white_ratio"] > max_white_ratio()


def test_pdf_evidence_crop_with_bbox(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_PDF_EVIDENCE_MAX_WHITE_RATIO", "0.99")
    pdf = build_rumore_decreto_pdf(
        tmp_path / "decreto.pdf", pages=3, prescription_page=2, pmc_page=3
    )
    session = tmp_path / "session"
    session.mkdir()

    out = pdf_evidence_crop_sync(
        pdf,
        session,
        page=2,
        # PyMuPDF origin is top-left; ReportLab synthetic text at y≈660pt from bottom → ~182pt from top
        bbox={"x0": 60, "y0": 160, "x1": 500, "y1": 220},
        caption="PIC [53]",
    )
    assert out["ok"] is True
    assert out["cropped"] is False
    assert len(out["bbox"]) == 4


def test_pdf_evidence_crop_increments_index(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_PDF_EVIDENCE_MAX_WHITE_RATIO", "0.99")
    pdf = build_rumore_decreto_pdf(
        tmp_path / "decreto.pdf", pages=2, prescription_page=1, pmc_page=2
    )
    session = tmp_path / "session"
    session.mkdir()

    first = pdf_evidence_crop_sync(pdf, session, page=1, caption="a")
    second = pdf_evidence_crop_sync(pdf, session, page=2, caption="b")
    assert first["ok"] and second["ok"]
    assert first["png_path"].endswith("e001.png")
    assert second["png_path"].endswith("e002.png")


def test_pdf_evidence_crop_uses_text_blocks_at_default_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_PDF_EVIDENCE_MAX_WHITE_RATIO", "0.90")
    pdf = build_rumore_decreto_pdf(
        tmp_path / "decreto.pdf",
        pages=5,
        prescription_page=3,
        pmc_page=4,
    )
    session = tmp_path / "session"
    session.mkdir()

    out = pdf_evidence_crop_sync(
        pdf,
        session,
        page=3,
        caption="decreto / §8.9 / pag. 3",
    )
    assert out["ok"] is True
    assert out["crop_method"] == "text_blocks"
    assert out["text_chars"] >= 80


def test_pdf_evidence_crop_invalid_page(tmp_path):
    pdf = build_rumore_decreto_pdf(
        tmp_path / "decreto.pdf", pages=2, prescription_page=1, pmc_page=2
    )
    session = tmp_path / "session"
    session.mkdir()

    out = pdf_evidence_crop_sync(pdf, session, page=0, caption="x")
    assert out["ok"] is False
    assert out["error"] == "invalid_page"

    out2 = pdf_evidence_crop_sync(pdf, session, page=99, caption="x")
    assert out2["ok"] is False
    assert out2["error"] == "page_out_of_range"
