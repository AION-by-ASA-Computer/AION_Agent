"""Testo utente/assistente da Haystack ChatMessage (API .text, non .content)."""
from __future__ import annotations

from haystack.dataclasses import ChatMessage


def chat_message_text(m: ChatMessage) -> str:
    """Restituisce il testo del messaggio; compatibile con Haystack 2.x."""
    t = getattr(m, "text", None)
    if t is not None:
        return str(t)
    legacy = getattr(m, "content", None)
    return str(legacy) if legacy is not None else ""
