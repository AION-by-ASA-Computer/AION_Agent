"""Tests for automatic PDF ingest on upload."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import UploadFile
from io import BytesIO

from src.benchmarks.long_document.synthetic import build_rumore_decreto_pdf
from src.session_workspace import save_upload, session_root
from src.tools.doc_auto_ingest import (
    auto_ingest_enabled,
    load_manifest,
    run_auto_ingest_background,
    schedule_auto_ingest,
)
from src.tools.doc_ingest import slugify_document_name


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_run_auto_ingest_writes_pages(data_dir):
    sid = "sess_auto_ingest"
    pdf_bytes = BytesIO()
    path = build_rumore_decreto_pdf(data_dir / "src.pdf", pages=30)
    meta = save_upload(sid, "decreto.pdf", path.read_bytes())

    await run_auto_ingest_background(sid, meta["relative_path"], meta["mime"])

    slug = slugify_document_name("decreto.pdf")
    pages = session_root(sid) / "derived" / "docs" / slug / "pages"
    assert len(list(pages.glob("p*.txt"))) == 30

    manifest = load_manifest(sid, meta["relative_path"])
    assert manifest is not None
    assert manifest.get("ok") is True
    assert manifest.get("pages_total") == 30


@pytest.mark.asyncio
async def test_schedule_auto_ingest_skips_non_pdf(data_dir):
    sid = "sess_txt"
    meta = save_upload(sid, "note.txt", b"hello world")

    async def _noop():
        return None

    # Should not raise; schedules only PDFs
    schedule_auto_ingest(sid, meta)
    await asyncio.sleep(0.05)
    slug_dir = session_root(sid) / "derived" / "docs"
    assert not slug_dir.exists() or not any(slug_dir.rglob("pages"))


@pytest.mark.asyncio
async def test_upload_endpoint_schedules_ingest(data_dir, monkeypatch):
    monkeypatch.setenv("AION_DOC_AUTO_INGEST", "1")
    from src.api.session_uploads import upload_session_files
    from src.api.auth_login import ChatAuthIdentity

    sid = "sess_upload_ep"
    pdf = build_rumore_decreto_pdf(data_dir / "u.pdf", pages=15)
    upload = UploadFile(filename="decreto.pdf", file=BytesIO(pdf.read_bytes()))

    class _Auth:
        identifier = "tester"

    result = await upload_session_files(sid, files=[upload], _auth=_Auth())
    assert len(result["files"]) == 1

    # Background task needs a tick
    await asyncio.sleep(0.5)

    rel = result["files"][0]["relative_path"]
    manifest = load_manifest(sid, rel)
    assert manifest is not None
    assert manifest.get("pages_total") == 15


def test_auto_ingest_disabled_by_env(monkeypatch):
    monkeypatch.setenv("AION_DOC_AUTO_INGEST", "0")
    assert auto_ingest_enabled() is False
