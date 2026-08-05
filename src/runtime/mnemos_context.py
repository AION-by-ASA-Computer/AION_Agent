"""Per-turn Mnemos context (scope binding, analogous to SQL QM)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

_turn_by_session: Dict[str, "MnemosTurnContext"] = {}


@dataclass
class MnemosTurnContext:
    session_id: str
    tenant_id: str
    user_id: str
    profile_slug: str
    project_slug: Optional[str] = None


def set_mnemos_turn_context(ctx: MnemosTurnContext) -> None:
    _turn_by_session[ctx.session_id] = ctx


def get_mnemos_turn_context(session_id: str) -> Optional[MnemosTurnContext]:
    return _turn_by_session.get(session_id)


def clear_mnemos_turn_context(session_id: str) -> None:
    _turn_by_session.pop(session_id, None)
