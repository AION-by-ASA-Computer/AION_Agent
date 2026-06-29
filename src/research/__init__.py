"""Deep Research engine (IterResearch-style), ported from Odysseus with AION adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .handler import ResearchHandler

__all__ = ["ResearchHandler", "get_research_handler", "deep_research_enabled"]


def __getattr__(name: str):
    if name == "ResearchHandler":
        from .handler import ResearchHandler

        return ResearchHandler
    if name == "get_research_handler":
        from .handler import get_research_handler

        return get_research_handler
    if name == "deep_research_enabled":
        from .handler import deep_research_enabled

        return deep_research_enabled
    raise AttributeError(name)
