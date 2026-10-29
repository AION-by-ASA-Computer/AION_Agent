"""Client minimo per la WhatsApp Cloud API (Graph API di Meta).

Un ``httpx.AsyncClient`` a vita breve per chiamata; ``transport`` è
iniettabile per i test (``httpx.MockTransport``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .config_service import graph_version

GRAPH_BASE_URL = "https://graph.facebook.com"
TIMEOUT_S = 15.0

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
    ) -> Dict[str, Any]:
        url = f"{self._base}/{self._version}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_S, transport=self._transport
            ) as client:
                resp = await client.request(
                    method, url, params=params, json=json, headers=headers
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

    async def send_text(
        self,
        phone_number_id: str,
        body: str,
        *,
        to: Optional[str] = None,
        recipient: Optional[str] = None,
        reply_to_wamid: Optional[str] = None,
    ) -> Optional[str]:
        """Invia un messaggio di testo e restituisce il ``wamid`` in uscita.

        ``to`` è il numero (``wa_id``); se manca si usa ``recipient`` (BSUID),
        perché il numero non arriva per gli utenti con username WhatsApp.
        """
        if not to and not recipient:
            raise GraphError("No recipient (phone or BSUID) for outbound message")
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        if to:
            payload["to"] = to
        else:
            payload["recipient"] = recipient
        if reply_to_wamid:
            payload["context"] = {"message_id": reply_to_wamid}
        data = await self._request("POST", f"{phone_number_id}/messages", json=payload)
        messages = data.get("messages") or []
        return (messages[0] or {}).get("id") if messages else None

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
