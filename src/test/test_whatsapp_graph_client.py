"""Graph client media calls (download/upload/send/read) against ``httpx.MockTransport``.

Covers the security-relevant bits of the media flow: the bearer token is only
sent to Meta media hosts and downloads are capped at ``max_bytes``.
"""

import json

import httpx
import pytest

from src.channels.whatsapp.graph_client import (
    GraphClient,
    GraphError,
    MediaTooLarge,
    is_allowed_media_url,
)
from src.test.whatsapp_test_helpers import ACCESS_TOKEN, PNID

LOOKASIDE = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=M1"


def _client(handler, seen):
    """GraphClient whose requests go to ``handler`` and are recorded in ``seen``."""

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return GraphClient(ACCESS_TOKEN, "v26.0", transport=httpx.MockTransport(_record))


def test_media_host_allowlist():
    """Only https URLs on Meta CDN hosts may receive the access token."""
    assert is_allowed_media_url(LOOKASIDE)
    assert is_allowed_media_url("https://mmg.whatsapp.net/v/t62/abc")
    assert not is_allowed_media_url("http://lookaside.fbsbx.com/x")
    assert not is_allowed_media_url("https://evil.example.com/fbsbx.com")
    assert not is_allowed_media_url("https://fbsbx.com.evil.example/x")
    assert not is_allowed_media_url(None)


@pytest.mark.anyio
async def test_download_sends_bearer_to_meta_host():
    seen = []
    client = _client(lambda r: httpx.Response(200, content=b"bytes"), seen)
    assert await client.download_media(LOOKASIDE, max_bytes=100) == b"bytes"
    assert seen[0].headers["authorization"] == f"Bearer {ACCESS_TOKEN}"


@pytest.mark.anyio
async def test_download_refuses_foreign_host_without_request():
    """A spoofed URL must not even be contacted (the token would leak)."""
    seen = []
    client = _client(lambda r: httpx.Response(200, content=b"x"), seen)
    with pytest.raises(GraphError):
        await client.download_media("https://evil.example.com/a.jpg", max_bytes=100)
    assert seen == []


@pytest.mark.anyio
async def test_download_aborts_past_max_bytes():
    """Both a declared Content-Length and the actual body are capped."""
    seen = []
    client = _client(lambda r: httpx.Response(200, content=b"x" * 50), seen)
    with pytest.raises(MediaTooLarge):
        await client.download_media(LOOKASIDE, max_bytes=10)

    # Chunked body without Content-Length: the received bytes are counted.
    async def _chunks():
        yield b"x" * 8
        yield b"x" * 8

    def chunked(request):
        return httpx.Response(200, content=_chunks())

    with pytest.raises(MediaTooLarge):
        await _client(chunked, []).download_media(LOOKASIDE, max_bytes=10)


@pytest.mark.anyio
async def test_download_http_error_carries_status():
    """404 = expired lookaside URL: the caller refreshes it via ``get_media``."""
    client = _client(lambda r: httpx.Response(404, json={}), [])
    with pytest.raises(GraphError) as exc:
        await client.download_media(LOOKASIDE, max_bytes=100)
    assert exc.value.status == 404


@pytest.mark.anyio
async def test_get_media_scopes_to_phone_number():
    seen = []
    client = _client(
        lambda r: httpx.Response(200, json={"url": LOOKASIDE, "file_size": 3}), seen
    )
    info = await client.get_media("M1", phone_number_id=PNID)
    assert info["url"] == LOOKASIDE
    assert seen[0].url.path == "/v26.0/M1"
    assert seen[0].url.params["phone_number_id"] == PNID


@pytest.mark.anyio
async def test_upload_media_is_multipart():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={"id": "UP1"}), seen)
    media_id = await client.upload_media(PNID, b"%PDF-1.4", "application/pdf", "r.pdf")
    assert media_id == "UP1"
    req = seen[0]
    assert req.url.path == f"/v26.0/{PNID}/media"
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.read()
    assert b'name="messaging_product"' in body and b"whatsapp" in body
    assert b'filename="r.pdf"' in body and b"%PDF-1.4" in body


@pytest.mark.anyio
async def test_upload_without_id_is_an_error():
    client = _client(lambda r: httpx.Response(200, json={}), [])
    with pytest.raises(GraphError):
        await client.upload_media(PNID, b"x", "image/png", "a.png")


@pytest.mark.anyio
async def test_send_media_payloads():
    """Documents carry ``filename``; captions are capped at 1024 characters."""
    seen = []
    client = _client(
        lambda r: httpx.Response(200, json={"messages": [{"id": "wamid.M"}]}), seen
    )
    wamid = await client.send_media(
        PNID, "document", "UP1", filename="report.xlsx", recipient="IT.1"
    )
    assert wamid == "wamid.M"
    doc = json.loads(seen[0].content)
    assert doc["type"] == "document"
    assert doc["document"] == {"id": "UP1", "filename": "report.xlsx"}
    assert doc["recipient"] == "IT.1" and "to" not in doc

    await client.send_media(
        PNID, "image", "UP2", caption="x" * 2000, filename="a.png", to="39333"
    )
    img = json.loads(seen[1].content)
    assert img["to"] == "39333"
    assert "filename" not in img["image"]
    assert len(img["image"]["caption"]) == 1024


@pytest.mark.anyio
async def test_mark_read_without_typing():
    seen = []
    client = _client(lambda r: httpx.Response(200, json={"success": True}), seen)
    await client.mark_read(PNID, "wamid.IN")
    body = json.loads(seen[0].content)
    assert body == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.IN",
    }
