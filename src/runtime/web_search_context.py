"""ContextVar per preferenze ricerca web per richiesta (toggle + host utente)."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class WebSearchRequestContext:
    enabled: bool = True
    restrict_hosts: Tuple[str, ...] = ()


_ctx: ContextVar[Optional[WebSearchRequestContext]] = ContextVar(
    "aion_web_search_request_ctx", default=None
)


def get_web_search_request_context() -> WebSearchRequestContext:
    c = _ctx.get()
    if c is None:
        return WebSearchRequestContext(enabled=True, restrict_hosts=())
    return c


def set_web_search_request_context(ctx: WebSearchRequestContext) -> Token:
    return _ctx.set(ctx)


def reset_web_search_request_context(token: Token) -> None:
    _ctx.reset(token)
