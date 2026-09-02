"""CI eval for document evidence crop (synthetic PDF, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.benchmarks.long_document.synthetic import build_rumore_decreto_pdf
from src.tools.pdf_evidence import pdf_evidence_crop_sync

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_CASES = REPO_ROOT / "evals" / "document_evidence" / "cases" / "smoke.yaml"


def _load_cases(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("cases") or [])


def _build_pdf(case: dict, work_dir: Path) -> Path:
    pdf_cfg = case.get("pdf") or {}
    assert pdf_cfg.get("source") == "synthetic"
    return build_rumore_decreto_pdf(
        work_dir / f"{case['id']}.pdf",
        pages=int(pdf_cfg.get("pages") or 10),
        prescription_page=int(pdf_cfg.get("prescription_page") or 5),
        pmc_page=int(pdf_cfg.get("pmc_page") or 8),
    )


@pytest.mark.parametrize("path", [SMOKE_CASES])
def test_document_evidence_dataset_schema(path: Path):
    assert path.is_file(), f"missing {path}"
    cases = _load_cases(path)
    assert cases, "no cases"
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for case in cases:
        assert case.get("crop"), f"{case['id']}: missing crop block"
        assert case.get("expect"), f"{case['id']}: missing expect block"


@pytest.mark.parametrize("case", _load_cases(SMOKE_CASES), ids=lambda c: c["id"])
def test_document_evidence_pipeline_case(case: dict, tmp_path, monkeypatch):
    monkeypatch.setenv("AION_PDF_EVIDENCE_MAX_WHITE_RATIO", "0.90")
    pdf = _build_pdf(case, tmp_path)
    session = tmp_path / "session"
    session.mkdir()

    crop_cfg = case["crop"]
    out = pdf_evidence_crop_sync(
        pdf,
        session,
        page=int(crop_cfg["page"]),
        full_page=bool(crop_cfg.get("full_page")),
        caption=str(crop_cfg.get("caption") or ""),
        source_relative_path=f"uploads/{pdf.name}",
    )

    expect = case["expect"]
    if expect.get("ok") is True:
        assert out["ok"] is True, out
        if expect.get("max_white_ratio") is not None:
            assert out["ok"] is True
            assert out["white_ratio"] <= float(expect["max_white_ratio"]) + 0.01
        if expect.get("min_width"):
            png = session / out["png_path"]
            from PIL import Image

            with Image.open(png) as img:
                assert img.width >= int(expect["min_width"])
        if expect.get("sidecar_required"):
            sidecar = session / out["sidecar_path"]
            assert sidecar.is_file()
        if expect.get("cropped") is not None:
            assert out.get("cropped") is expect["cropped"]
    else:
        assert out["ok"] is False, out
        if expect.get("error"):
            assert out.get("error") == expect["error"]
