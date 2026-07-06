"""Resolve chat UI language from DB and build system-prompt instructions."""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger("aion.user_language")

SUPPORTED_UI_LANGUAGES = frozenset({"it", "en", "es", "fr", "de"})

LANG_DISPLAY_NAMES = {
    "it": "Italiano",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
}


def normalize_ui_language(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    low = str(code).strip().lower().split("-")[0]
    return low if low in SUPPORTED_UI_LANGUAGES else None


def default_ui_language() -> str:
    """Server fallback when the user has no saved preference (browser default is set client-side)."""
    return normalize_ui_language(os.getenv("AION_DEFAULT_UI_LANGUAGE")) or "en"


async def load_user_ui_language(user_id: str) -> Optional[str]:
    """Load UI language from ``users.metadata_json.language`` (saved by chat-ui)."""
    if not user_id or user_id == "default":
        return None
    try:
        from sqlalchemy import select

        from src.data.engine import get_async_session_maker
        from src.data.models import User

        async with get_async_session_maker()() as session:
            rows = (
                (await session.execute(select(User).where(User.identifier == user_id)))
                .scalars()
                .all()
            )
            user = rows[0] if rows else None
            if not user or not user.metadata_json:
                return None
            meta = json.loads(user.metadata_json)
            return normalize_ui_language(meta.get("language"))
    except Exception as exc:
        logger.warning("Failed to load user UI language for %s: %s", user_id, exc)
        return None


def build_ui_language_prompt_section(lang: str) -> str:
    code = normalize_ui_language(lang) or default_ui_language()
    name = LANG_DISPLAY_NAMES.get(code, code)
    return (
        f"\n\n## Response language\n"
        f"The user set their chat UI language to {name} ({code}). "
        f"Always reply to the user in {name} (chat prose, summaries, explanations).\n"
        f"**Exception — internal thinking/reasoning blocks must stay in English** "
        f"(short checklist per core_protocol). Do not write thinking in {name}."
    )


def resolve_compaction_language(user_id: str, db_lang: Optional[str]) -> str:
    """Language for STM compaction summaries: DB preference, else server default."""
    return normalize_ui_language(db_lang) or default_ui_language()
