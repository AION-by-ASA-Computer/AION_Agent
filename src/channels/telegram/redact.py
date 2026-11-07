"""Redazione dei token Telegram da testi e log.

Un token bot ha forma ``<bot_id>:<35 caratteri>`` e compare anche negli URL
della Bot API (``/bot<token>/getUpdates``), quindi può finire in messaggi di
eccezione di aiohttp. Il filtro va installato su ogni logger che può vederli.
"""

from __future__ import annotations

import logging
import re

# Niente \b iniziale: in "/bot<token>" fra "t" e la prima cifra non c'è word boundary.
_TOKEN_RE = re.compile(r"(?<![0-9])\d{5,16}:[A-Za-z0-9_-]{30,}")
_REDACTED = "<telegram-token-redacted>"

# Logger di aiogram (aiogram/loggers.py) e del canale.
_LOGGER_NAMES = (
    "aiogram",
    "aiogram.dispatcher",
    "aiogram.event",
    "aiogram.middlewares",
    "aiogram.webhook",
    "aiogram.scene",
    "aion.telegram",
)


def redact(text: object) -> str:
    return _TOKEN_RE.sub(_REDACTED, str(text))


class TokenRedactingFilter(logging.Filter):
    """Riscrive messaggio ed eccezione del record senza token."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 — format errato: lascia il record com'è
            return True
        record.msg = redact(msg)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
            # exc_text già calcolato e redatto: evita che il formatter rigeneri il traceback.
            record.exc_info = None
        return True


_FILTER = TokenRedactingFilter()


def install_log_redaction() -> None:
    """Idempotente: aggiunge il filtro ai logger di aiogram e del canale."""
    for name in _LOGGER_NAMES:
        lg = logging.getLogger(name)
        if _FILTER not in lg.filters:
            lg.addFilter(_FILTER)
