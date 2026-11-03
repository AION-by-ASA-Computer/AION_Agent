"""Gateway Telegram attivo nel processo (uno solo: uvicorn gira con --workers 1).

Lo usa l'API ``/v1/me/telegram`` per costruire il link di collegamento
(username del bot manager) e per notificare lo scollegamento su Telegram.
Modulo senza import di aiogram.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.channels.telegram.gateway import TelegramGateway

_gateway: Optional["TelegramGateway"] = None


def set_gateway(gateway: Optional["TelegramGateway"]) -> None:
    global _gateway
    _gateway = gateway


def get_gateway() -> Optional["TelegramGateway"]:
    return _gateway


def manager_username() -> Optional[str]:
    """Username del bot manager, noto solo dopo il getMe riuscito all'avvio."""
    gw = _gateway
    return gw.bot_username if gw is not None else None
