import io
import json
import zipfile
import pytest

from src.session_workspace import session_root
from src.tools.office_extract import extract_docx_content


def _create_dummy_docx() -> bytes:
    """Create a minimal valid docx in-memory with text, headings, and an image reference."""
    doc_xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
            xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
            xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>1. INTRODUZIONE E OBIETTIVI</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Questo è il testo descrittivo del capitolo 1.</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Figura 1.1 – Schema dell'impianto</w:t></w:r>
    </w:p>
    <w:p>
      <w:r>
        <w:drawing>
          <wp:inline>
            <wp:docPr id="1" name="Immagine 1" title="Schema"/>
            <a:graphic>
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                <pic:pic>
                  <pic:blipFill>
                    <a:blip r:embed="rId2"/>
                  </pic:blipFill>
                </pic:pic>
              </a:graphicData>
            </a:graphic>
          </wp:inline>
        </w:drawing>
      </w:r>
    </w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Colonna 1</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Colonna 2</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Valore A</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Valore B</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>
</Relationships>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))
        zf.writestr("word/_rels/document.xml.rels", rels_xml.encode("utf-8"))
        zf.writestr("word/media/image1.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfake")
    return buf.getvalue()


def test_office_extract_docx_content(tmp_path, monkeypatch):
    session_id = "test_extract_session"
    sroot = tmp_path / "sessions" / session_id
    sroot.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))

    uploads = sroot / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    docx_file = uploads / "test_report.docx"
    docx_file.write_bytes(_create_dummy_docx())

    res = extract_docx_content(session_id, "uploads/test_report.docx", extract_images=True)

    assert res["ok"] is True
    assert res["stats"]["total_paragraphs"] >= 4
    assert res["stats"]["total_tables"] == 1
    assert res["stats"]["total_images_extracted"] == 1

    # Check outline
    assert len(res["outline"]) == 1
    assert "1. INTRODUZIONE E OBIETTIVI" in res["outline"][0]["title"]

    # Check image catalog and contextual reference
    images = res["images_catalog"]
    assert len(images) == 1
    img = images[0]
    assert img["media_filename"] == "image1.png"
    assert "Figura 1.1" in img["caption_or_adjacent_text"]
    assert "INTRODUZIONE" in img["heading_context"]
    assert "derived/extracted_images/test_report" in img["saved_relative_path"]

    # Check generated artifacts
    full_text_path = sroot / res["artifacts"]["full_text_file"]
    assert full_text_path.is_file()
    text_content = full_text_path.read_text(encoding="utf-8")
    assert "1. INTRODUZIONE E OBIETTIVI" in text_content
    assert "Valore A | Valore B" in text_content

    # Verify grep compatibility
    from src.tools.session_fs_tools import grep_content
    grep_res = grep_content(sroot, sroot / "derived", "INTRODUZIONE", fixed_string=True)
    assert len(grep_res) >= 1
    assert any("test_report_full.txt" in r["file"] for r in grep_res)

    struct_path = sroot / res["artifacts"]["structure_json"]
    assert struct_path.is_file()
    struct_json = json.loads(struct_path.read_text(encoding="utf-8"))
    assert len(struct_json["paragraphs"]) >= 4
    assert len(struct_json["tables"]) == 1
    assert len(struct_json["images"]) == 1
