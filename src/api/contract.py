"""Route del contratto API usate da AION SRE.

Per queste route valgono le regole di ``docs/api-and-runtime/rest-api.md``
(sezione "API contract"): solo aggiunte compatibili, preavviso con header
``Deprecation``/``Sunset`` prima di rimuovere o cambiare un campo. L'elenco è
usato dai test del contratto, dallo snapshot OpenAPI
(``scripts/export_openapi.py``) e dalla documentazione.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.api.auth.scopes import Scope


@dataclass(frozen=True)
class ContractRoute:
    method: str
    path: str
    scope: str
    kind: Literal["json", "sse"] = "json"


CONTRACT_ROUTES: tuple[ContractRoute, ...] = (
    ContractRoute("POST", "/v1/conversations", Scope.CONVERSATIONS_WRITE),
    ContractRoute("POST", "/v1/chat/stream", Scope.CHAT, "sse"),
    ContractRoute(
        "GET", "/v1/chat/stream/reconnect/{conversation_id}", Scope.CHAT, "sse"
    ),
    ContractRoute("POST", "/v1/chat/stop", Scope.CHAT),
    ContractRoute(
        "GET",
        "/chat-ui/conversations/{conv_id}/stream-status",
        Scope.CONVERSATIONS_READ,
    ),
    ContractRoute(
        "GET", "/chat-ui/conversations/{conv_id}/messages", Scope.CONVERSATIONS_READ
    ),
    ContractRoute(
        "POST",
        "/chat-ui/conversations/{conv_id}/messages/{message_id}/rate",
        Scope.CONVERSATIONS_WRITE,
    ),
    ContractRoute("GET", "/sessions/{session_id}/charts", Scope.CHAT),
    ContractRoute(
        "GET", "/v1/conversations/{conversation_id}/steps", Scope.CONVERSATIONS_READ
    ),
    ContractRoute("GET", "/profiles", Scope.CHAT),
)
