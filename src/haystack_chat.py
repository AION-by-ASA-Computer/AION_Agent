"""Testo utente/assistente da Haystack ChatMessage (API .text, non .content)."""

from __future__ import annotations

from haystack.dataclasses import ChatMessage


def chat_message_text(m: ChatMessage) -> str:
    """Restituisce il testo del messaggio; compatibile con Haystack 2.x (inclusi tool result)."""
    t = getattr(m, "text", None)
    if t is not None and str(t).strip():
        return str(t)
    content = getattr(m, "_content", None) or getattr(m, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            piece = getattr(part, "text", None)
            if piece is not None and str(piece).strip():
                parts.append(str(piece))
                continue
            result = getattr(part, "result", None)
            if result is not None and str(result).strip():
                parts.append(str(result))
        if parts:
            return "\n".join(parts)
    legacy = getattr(m, "content", None)
    return str(legacy) if legacy is not None else ""
