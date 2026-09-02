"""Tests for legacy Word (.doc) conversion on upload."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.session_workspace import save_upload, session_root
from src.tools.office_convert import (
    convert_legacy_word_sync,
    find_soffice,
    is_legacy_word_upload,
    is_misnamed_docx,
)


def test_is_legacy_word_upload_by_extension():
    assert is_legacy_word_upload("report.doc", "application/octet-stream")
    assert not is_legacy_word_upload("report.docx", "application/octet-stream")


def test_is_misnamed_docx_detects_zip():
    buf = b"PK\x03\x04" + b"0" * 100
    assert is_misnamed_docx("file.doc", buf) is True
    assert is_misnamed_docx("file.doc", b"\xd0\xcf\x11\xe0" + b"0" * 100) is False


def test_convert_misnamed_docx_copies_as_docx(tmp_path, monkeypatch):
    sid = "test-legacy-word-01"
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))

    minimal_docx = tmp_path / "mini.docx"
    with zipfile.ZipFile(minimal_docx, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")

    meta = save_upload(sid, "report.doc", minimal_docx.read_bytes())
    out = convert_legacy_word_sync(sid, meta)

    assert out.get("conversion_status") == "ok"
    assert out.get("conversion_method") == "rename_zip"
    conv = out.get("converted_docx_path")
    assert conv and conv.endswith(".docx")
    conv_path = session_root(sid) / conv
    assert conv_path.is_file()
    with zipfile.ZipFile(conv_path) as zf:
        assert "word/document.xml" in zf.namelist()


def test_convert_legacy_word_unavailable_without_soffice(tmp_path, monkeypatch):
    sid = "test-legacy-word-02"
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AION_SOFFICE_PATH", raising=False)

    ole_doc = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
    meta = save_upload(sid, "legacy.doc", ole_doc)

    with patch("src.tools.office_convert.find_soffice", return_value=None):
        out = convert_legacy_word_sync(sid, meta)

    assert out.get("conversion_status") == "unavailable"
    assert "LibreOffice" in (out.get("conversion_error") or "")


def test_convert_legacy_word_with_soffice_mock(tmp_path, monkeypatch):
    sid = "test-legacy-word-03"
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))

    ole_doc = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
    meta = save_upload(sid, "report.doc", ole_doc)

    def fake_run(cmd, **kwargs):
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        src = Path(cmd[-1])
        (outdir / f"{src.stem}.docx").write_bytes(b"PK\x03\x04" + b"fake-docx-bytes")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with patch(
        "src.tools.office_convert.find_soffice", return_value="/usr/bin/soffice"
    ):
        with patch("src.tools.office_convert.subprocess.run", side_effect=fake_run):
            out = convert_legacy_word_sync(sid, meta)

    assert out.get("conversion_status") == "ok"
    assert out.get("converted_docx_path", "").endswith("report.docx")
    conv_path = session_root(sid) / str(out["converted_docx_path"])
    assert conv_path.is_file()


@pytest.mark.skipif(
    find_soffice() is None,
    reason="LibreOffice not installed — skip live conversion",
)
def test_find_soffice_live():
    assert find_soffice()
