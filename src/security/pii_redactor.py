"""Optional PII redaction (regex placeholders) — hook logs matches; safe mutation best-effort."""

from __future__ import annotations

import logging
import os
import re
from typing import Tuple

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.runtime.hooks import HookContext

logger = logging.getLogger("aion.pii")

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE_IT = re.compile(r"\b(?:\+39\s?)?3\d{2}[\s.-]?\d{6,7}\b")
_CF_IT = re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.I)


def redact_text(text: str) -> Tuple[str, int]:
    if os.getenv("AION_PII_REDACT", "1").lower() not in ("1", "true", "yes"):
        return text, 0
    n = 0
    out = text
    for pat, label in (
        (_EMAIL, "[EMAIL_REDACTED]"),
        (_PHONE_IT, "[PHONE_REDACTED]"),
        (_CF_IT, "[CF_REDACTED]"),
    ):
        out, c = pat.subn(label, out)
        n += c
    return out, n


async def pii_pre_llm_hook(ctx: HookContext) -> None:
    if ctx.event != "pre_llm_call":
        return
    msgs = ctx.payload.get("messages") or []
    for m in msgs:
        if not isinstance(m, ChatMessage):
            continue
        role = getattr(getattr(m, "role", None), "value", m.role)
        if "user" not in str(role).lower():
            continue
        t = chat_message_text(m)
        nt, n = redact_text(t)
        if not n:
            continue
        try:
            m.text = nt  # type: ignore[attr-defined]
        except Exception:
            logger.info(
                "PII redaction matched %d pattern(s); Haystack message not mutated in-place",
                n,
            )
