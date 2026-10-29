"""``channels.whatsapp.media``: inbound ingest and outbound file selection/sending.

Uses a temporary ``AION_DATA_DIR`` and stubs the storage backend and the PDF
auto-ingest, so nothing is written outside ``tmp_path``.
"""

import base64
import hashlib
import os

import pytest

from src.channels.whatsapp import media
from src.channels.whatsapp.graph_client import GraphError, MediaTooLarge
from src.channels.whatsapp.payload import InboundMedia
from src.test.whatsapp_test_helpers import PNID, FakeGraph

CID = "conv-media-1"


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    """Isolated session storage + no-op storage backend / auto-ingest."""
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path / "data"))
    stored = []

    class _Backend:
        def put_bytes(self, key, data, mime):
            stored.append((key, data, mime))

    monkeypatch.setattr(media, "get_storage_backend", lambda: _Backend())
    monkeypatch.setattr(media, "schedule_auto_ingest", lambda cid, meta: None)
    return stored


class _ExpiringGraph(FakeGraph):
    """The webhook URL is expired (404); the one from ``get_media`` works."""

    async def download_media(self, url, *, max_bytes):
        self.downloaded.append(url)
        if "mid=" not in url:
            raise GraphError("expired", status=404)
        return self.media_bytes


def test_inbound_filename():
    """Documents keep their name (+ extension from MIME); photos get a timestamp."""
    doc = InboundMedia(id="1", mime_type="application/pdf", filename="Fattura")
    assert media.inbound_filename("document", doc) == "Fattura.pdf"
    doc = InboundMedia(id="1", mime_type="application/pdf", filename="../a/b.xlsx")
    assert media.inbound_filename("document", doc) == "b.xlsx"
    photo = media.inbound_filename("image", InboundMedia(id="1", mime_type="image/png"))
    assert photo.startswith("whatsapp_") and photo.endswith(".png")


def test_sha256_accepts_hex_and_base64():
    data = b"hello"
    digest = hashlib.sha256(data).digest()
    assert media._sha256_matches(data, digest.hex())
    assert media._sha256_matches(data, base64.b64encode(digest).decode())
    assert media._sha256_matches(data, None)
    assert not media._sha256_matches(data, "abc")


@pytest.mark.anyio
async def test_ingest_saves_upload_and_storage_copy(data_dir, caplog):
    """The file lands in ``uploads/``; a sha256 mismatch is logged, not fatal."""
    from src.session_workspace import session_root

    graph = FakeGraph()
    meta = await media.ingest_inbound_media(
        graph,
        tenant_id="default",
        phone_number_id=PNID,
        conversation_id=CID,
        msg_type="image",
        media=InboundMedia(id="M9", mime_type="image/png", sha256="abc"),
    )
    assert meta["relative_path"].startswith("uploads/")
    assert meta["mime"] == "image/png"
    path = session_root(CID) / meta["relative_path"]
    assert path.read_bytes() == graph.media_bytes
    (key, data, _mime) = data_dir[0]
    assert key.startswith(f"default/conversations/{CID}/uploads/")
    assert meta["storage_key"] == key and data == graph.media_bytes
    assert "sha256 mismatch" in caplog.text


@pytest.mark.anyio
async def test_ingest_refreshes_expired_url(data_dir):
    graph = _ExpiringGraph()
    stale = "https://lookaside.fbsbx.com/whatsapp_business/attachments/old"
    await media.ingest_inbound_media(
        graph,
        tenant_id="default",
        phone_number_id=PNID,
        conversation_id=CID,
        msg_type="document",
        media=InboundMedia(
            id="M2", mime_type="application/pdf", filename="a.pdf", url=stale
        ),
    )
    assert graph.downloaded[0] == stale
    assert "mid=M2" in graph.downloaded[1]


@pytest.mark.anyio
async def test_ingest_errors(data_dir):
    """Unsupported type, too large and Graph failures map to typed errors."""
    graph = FakeGraph()
    kwargs = dict(tenant_id="default", phone_number_id=PNID, conversation_id=CID)
    with pytest.raises(media.UnsupportedMedia):
        await media.ingest_inbound_media(
            graph, msg_type="audio", media=InboundMedia(id="A"), **kwargs
        )
    graph.download_error = MediaTooLarge("big")
    with pytest.raises(MediaTooLarge):
        await media.ingest_inbound_media(
            graph, msg_type="image", media=InboundMedia(id="B"), **kwargs
        )
    graph.download_error = GraphError("boom", status=500)
    with pytest.raises(media.MediaIngestError):
        await media.ingest_inbound_media(
            graph, msg_type="image", media=InboundMedia(id="C"), **kwargs
        )


def test_output_snapshot_filters_internal_files(data_dir):
    """Only user-facing deliverables created/changed during the turn are picked."""
    from src.session_workspace import session_root

    root = session_root(CID)

    def write(rel, content=b"x"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    old = write("workspace/old.csv")
    before = media.snapshot_outputs(CID)

    write("workspace/report.xlsx")
    write("derived/chart.png")
    write("workspace/script.py")
    write("workspace/.versions/report.xlsx.1")
    write("derived/tool_results/r.txt")
    write("derived/docs/page_1.md")
    write("uploads/input.pdf")
    # Rewritten during the turn -> counts as a new output.
    os.utime(old, ns=(old.stat().st_atime_ns, old.stat().st_mtime_ns + 10**9))

    after = media.snapshot_outputs(CID)
    new = media.collect_new_outputs(before, after)
    assert sorted(new) == [
        "derived/chart.png",
        "workspace/old.csv",
        "workspace/report.xlsx",
    ]


def test_outbound_kind(monkeypatch):
    monkeypatch.delenv("AION_WHATSAPP_MAX_OUTBOUND_BYTES", raising=False)
    mb = 1024 * 1024
    assert media.outbound_kind("image/png", mb) == ("image", "image/png")
    # Over Meta's 5 MB image cap: still deliverable as a document.
    assert media.outbound_kind("image/jpeg", 6 * mb) == ("document", "image/jpeg")
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert media.outbound_kind(xlsx, mb) == ("document", xlsx)
    assert media.outbound_kind("text/csv", 10) == ("document", "text/plain")
    assert media.outbound_kind("application/zip", 10) is None
    monkeypatch.setenv("AION_WHATSAPP_MAX_OUTBOUND_BYTES", "100")
    assert media.outbound_kind("application/pdf", 200) is None


@pytest.mark.anyio
async def test_send_outputs_respects_budget(data_dir, monkeypatch):
    """Files past the limit, unsupported or rejected by Meta are counted as left out."""
    from src.session_workspace import session_root

    monkeypatch.setenv("AION_WHATSAPP_MAX_OUTBOUND_FILES", "2")
    root = session_root(CID)
    files = ["workspace/a.pdf", "workspace/b.zip", "workspace/c.png", "workspace/d.csv"]
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"data")

    class _Replier:
        def __init__(self):
            self.sent = []

        async def send_media(self, kind, data, mime, filename):
            if filename == "c.png":
                raise GraphError("rejected", code="131053")
            self.sent.append((kind, mime, filename))

    replier = _Replier()
    sent, left_out = await media.send_outputs(replier, CID, files)
    # a.pdf sent; b.zip unsupported; c.png rejected; d.csv sent -> budget hit.
    assert replier.sent == [
        ("document", "application/pdf", "a.pdf"),
        ("document", "text/plain", "d.csv"),
    ]
    assert (sent, left_out) == (2, 2)

    replier = _Replier()
    sent, left_out = await media.send_outputs(
        replier, CID, ["workspace/a.pdf", "workspace/d.csv", "workspace/a.pdf"]
    )
    assert (sent, left_out) == (2, 1)
