import logging
import os
import re
from typing import Any, Dict, Optional

from ..skill_registry import skill_registry
from .llm_extract import complete_json_async
from .mnemos.orchestrator import mnemos_orchestrator
from .mnemos.scope import default_tenant_id, sanitize_project_slug

logger = logging.getLogger("aion.memory.ltm")

_LTM_CTX_CHARS = int(os.getenv("AION_LTM_CONTEXT_MAX_CHARS", "4000"))
_LTM_ASST_CHARS = int(os.getenv("AION_LTM_EXTRACT_ASSISTANT_MAX_CHARS", "8000"))
_LTM_BATCH_CHARS = int(os.getenv("AION_LTM_BATCH_TRANSCRIPT_MAX_CHARS", "16000"))


def sanitize_id(part: str) -> str:
    s = re.sub(r"[^a-z0-9_\-]", "_", (part or "default").lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:80] or "default"


class LTMOrchestrator:
    """Long-term memory via AION Mnemos (native SQLite backend)."""

    def __init__(self, agent_name: Optional[str] = None):
        self.agent_name = agent_name or os.getenv("AION_LTM_AGENT_NAME", "AION")

    async def wake_up(
        self,
        chat_session_id: str,
        *,
        user_id: str = "default",
        tenant_id: Optional[str] = None,
        active_project: Optional[str] = None,
    ) -> str:
        tid = tenant_id or default_tenant_id()
        project = (active_project or "").strip() or None
        try:
            text = await mnemos_orchestrator.wake_up(
                tenant_id=tid,
                user_id=user_id,
                active_project_slug=project,
            )
            logger.info("Mnemos wake_up ok (%d chars)", len(text))
            return text
        except Exception as e:
            logger.warning("Mnemos wake_up failed: %s", e)
            return ""

    async def precompact_flush(
        self,
        chat_session_id: str,
        user_id: str,
        head_transcript: str,
        *,
        active_project: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        await self.extract_and_persist(
            chat_session_id,
            user_id,
            head_transcript,
            "",
            mode="batch",
            active_project=active_project,
            tenant_id=tenant_id,
        )

    def _extraction_skill_text(self) -> str:
        return (
            skill_registry.get_skill("ltm_note_extraction")
            or skill_registry.get_skill("ltm_extraction")
            or ""
        )

    async def extract_and_persist(
        self,
        session_id: str,
        user_id: str,
        user_input: str,
        assistant_output: str,
        *,
        mode: str = "turn",
        active_project: Optional[str] = None,
        profile_slug: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_message_id: Optional[str] = None,
        assistant_message_id: Optional[str] = None,
    ) -> None:
        _ = profile_slug
        if os.getenv("AION_LTM_EXTRACT", "1").lower() in ("0", "false", "no"):
            return
        system = self._extraction_skill_text()
        if not system:
            system = "Rispondi solo con JSON valido secondo lo schema LTM note."
        ctx_prefix = ""
        if active_project and sanitize_project_slug(active_project) != "default":
            ctx_prefix = f"ACTIVE_PROJECT: {sanitize_project_slug(active_project)}\n\n"
        if mode == "batch":
            user_prompt = (
                ctx_prefix
                + "\nModalità: consolidamento batch — sintetizza senza duplicare.\n"
                + "TRANSCRIPT:\n"
                + user_input[:_LTM_BATCH_CHARS]
            )
        else:
            user_prompt = ctx_prefix + (
                "USER_INPUT:\n"
                + user_input[:_LTM_CTX_CHARS]
                + "\n\nASSISTANT_OUTPUT:\n"
                + assistant_output[:_LTM_ASST_CHARS]
            )
        try:
            data = await complete_json_async(system, user_prompt)
        except Exception as e:
            logger.warning("LTM extraction LLM failed: %s", e)
            return
        tid = tenant_id or default_tenant_id()
        await mnemos_orchestrator.apply_extraction(
            data,
            tenant_id=tid,
            user_id=user_id,
            active_project_slug=active_project,
            source_session_id=session_id,
            source_message_id=assistant_message_id or user_message_id,
        )

    def build_augmented_user_text(
        self, user_input: str, ltm_context: str, wake_raw: str
    ) -> str:
        if os.getenv("AION_LTM_PREFIX_IN_USER", "1").lower() in ("0", "false", "no"):
            return user_input
        wake_short = (wake_raw or "").strip()
        if not wake_short:
            return user_input
        if len(wake_short) > int(os.getenv("AION_LTM_WAKE_MAX_CHARS", "4000")):
            wake_short = wake_short[
                : int(os.getenv("AION_LTM_WAKE_MAX_CHARS", "4000"))
            ]
        return f"[session_memory]\n{wake_short}\n\n{user_input}"


ltm_orchestrator = LTMOrchestrator()
