"""Client minimo per la WhatsApp Cloud API (Graph API di Meta).

Un ``httpx.AsyncClient`` a vita breve per chiamata; ``transport`` è
iniettabile per i test (``httpx.MockTransport``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from .config_service import graph_version

GRAPH_BASE_URL = "https://graph.facebook.com"
TIMEOUT_S = 15.0
# Media upload/download can move up to 100 MB: give them a longer budget.
MEDIA_TIMEOUT_S = 120.0

# Hosts allowed to receive our bearer token when downloading media. Meta serves
# media from ``lookaside.fbsbx.com``; the token must never reach any other host,
# even if a (signed) payload carried a different ``url``.
MEDIA_HOST_SUFFIXES = (".fbsbx.com", ".facebook.com", ".whatsapp.net")

PHONE_FIELDS = (
    "display_phone_number,verified_name,quality_rating,platform_type,"
    "code_verification_status,name_status"
)


class GraphError(Exception):
    """Errore restituito da Meta (``error.code``) o di rete (``code=None``)."""

    def __init__(
        self,
        message: str,
        *,
        code: Optional[int] = None,
        subcode: Optional[int] = None,
        status: Optional[int] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.subcode = subcode
        self.status = status

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}" if self.code else self.message


def _error_from_response(resp: httpx.Response) -> GraphError:
    try:
        err = (resp.json() or {}).get("error") or {}
    except ValueError:
        err = {}
    details = ((err.get("error_data") or {}).get("details") or "").strip()
    message = (err.get("message") or f"HTTP {resp.status_code}").strip()
    if details and details not in message:
        message = f"{message} — {details}"
    return GraphError(
        message,
        code=err.get("code"),
        subcode=err.get("error_subcode"),
        status=resp.status_code,
    )


class MediaTooLarge(GraphError):
    """The media exceeds the size we accept (checked while streaming)."""


def is_allowed_media_url(url: Optional[str]) -> bool:
    """True when ``url`` is an https URL on a Meta media host."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host.endswith(suffix) for suffix in MEDIA_HOST_SUFFIXES
    )


class GraphClient:
    def __init__(
        self,
        access_token: str,
        version: Optional[str] = None,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        base_url: str = GRAPH_BASE_URL,
    ):
        self._token = access_token
        self._version = version or graph_version()
        self._transport = transport
        self._base = base_url.rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: float = TIMEOUT_S,
    ) -> Dict[str, Any]:
        url = f"{self._base}/{self._version}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with httpx.AsyncClient(
                timeout=timeout, transport=self._transport
            ) as client:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    files=files,
                    headers=headers,
                )
        except httpx.HTTPError as e:
            raise GraphError(f"Graph API unreachable: {e}") from e
        if resp.status_code >= 400:
            raise _error_from_response(resp)
        try:
            return resp.json() or {}
        except ValueError:
            return {}

    async def get_phone_info(self, phone_number_id: str) -> Dict[str, Any]:
        return await self._request(
            "GET", phone_number_id, params={"fields": PHONE_FIELDS}
        )

    async def get_subscribed_apps(self, waba_id: str) -> List[Dict[str, Any]]:
        data = await self._request("GET", f"{waba_id}/subscribed_apps")
        return list(data.get("data") or [])

    async def subscribe_app(self, waba_id: str) -> bool:
        data = await self._request("POST", f"{waba_id}/subscribed_apps")
        return bool(data.get("success"))

    async def _send_message(
        self,
        phone_number_id: str,
        payload: Dict[str, Any],
        *,
        to: Optional[str],
        recipient: Optional[str],
    ) -> Optional[str]:
        """POST a message payload to ``/messages`` and return the outbound ``wamid``.

        ``to`` is the phone number (``wa_id``); without it ``recipient`` (BSUID)
        is used, because the number is missing for users with a WhatsApp username.
        """
        if not to and not recipient:
            raise GraphError("No recipient (phone or BSUID) for outbound message")
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            **payload,
        }
        if to:
            payload["to"] = to
        else:
            payload["recipient"] = recipient
        data = await self._request("POST", f"{phone_number_id}/messages", json=payload)
        messages = data.get("messages") or []
        return (messages[0] or {}).get("id") if messages else None

    async def send_text(
        self,
        phone_number_id: str,
        body: str,
        *,
        to: Optional[str] = None,
        recipient: Optional[str] = None,
        reply_to_wamid: Optional[str] = None,
    ) -> Optional[str]:
        """Invia un messaggio di testo e restituisce il ``wamid`` in uscita."""
        payload: Dict[str, Any] = {
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        if reply_to_wamid:
            payload["context"] = {"message_id": reply_to_wamid}
        return await self._send_message(
            phone_number_id, payload, to=to, recipient=recipient
        )

    async def send_media(
        self,
        phone_number_id: str,
        kind: str,
        media_id: str,
        *,
        caption: Optional[str] = None,
        filename: Optional[str] = None,
        to: Optional[str] = None,
        recipient: Optional[str] = None,
    ) -> Optional[str]:
        """Send an uploaded media (``kind`` = image|document|...) by media id.

        ``filename`` only applies to documents: WhatsApp shows it and picks
        the file icon from its extension. ``caption`` is capped by Meta at
        1024 characters (not allowed on audio/sticker).
        """
        obj: Dict[str, Any] = {"id": media_id}
        if caption:
            obj["caption"] = caption[:1024]
        if filename and kind == "document":
            obj["filename"] = filename
        return await self._send_message(
            phone_number_id, {"type": kind, kind: obj}, to=to, recipient=recipient
        )

    async def get_media(
        self, media_id: str, *, phone_number_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Media metadata: ``{url, mime_type, sha256, file_size, id}``.

        The returned ``url`` expires after 5 minutes. Passing
        ``phone_number_id`` makes Meta check the media belongs to our number.
        """
        params = {"phone_number_id": phone_number_id} if phone_number_id else None
        return await self._request("GET", media_id, params=params)

    async def download_media(self, url: str, *, max_bytes: int) -> bytes:
        """Download a media URL with the bearer token, aborting past ``max_bytes``.

        Raises ``GraphError`` for non-Meta hosts (the token must not leak),
        HTTP errors (``status`` set, e.g. 404 = expired URL) and network
        failures; ``MediaTooLarge`` when the body exceeds ``max_bytes``.
        """
        if not is_allowed_media_url(url):
            raise GraphError("Media URL host not allowed")
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with httpx.AsyncClient(
                timeout=MEDIA_TIMEOUT_S, transport=self._transport
            ) as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        raise _error_from_response(resp)
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise MediaTooLarge("Media too large")
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        # Content-Length may be missing or wrong: enforce the
                        # cap on the bytes actually received too.
                        if len(buf) > max_bytes:
                            raise MediaTooLarge("Media too large")
                    return bytes(buf)
        except httpx.HTTPError as e:
            raise GraphError(f"Media download failed: {e}") from e

    async def upload_media(
        self, phone_number_id: str, data: bytes, mime: str, filename: str
    ) -> str:
        """Upload bytes to ``/{phone_number_id}/media`` and return the media id.

        Uploaded media live 30 days on Meta; we send them right away by id
        (Meta advises against ``link`` for throughput reasons).
        """
        resp = await self._request(
            "POST",
            f"{phone_number_id}/media",
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": (filename, data, mime)},
            timeout=MEDIA_TIMEOUT_S,
        )
        media_id = resp.get("id")
        if not media_id:
            raise GraphError("Media upload returned no id")
        return str(media_id)

    async def mark_read(self, phone_number_id: str, wamid: str) -> None:
        """Blue ticks only, without "typing…" (used when no reply follows)."""
        await self._request(
            "POST",
            f"{phone_number_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": wamid,
            },
        )

    async def mark_read_typing(self, phone_number_id: str, wamid: str) -> None:
        """Spunte blu + indicatore "sta scrivendo…" (dura max 25s o fino alla risposta)."""
        await self._request(
            "POST",
            f"{phone_number_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": wamid,
                "typing_indicator": {"type": "text"},
            },
        )
