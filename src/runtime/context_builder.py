"""Unified context assembly (Pi-inspired transformContext + convertToLlm)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from haystack.dataclasses import ChatMessage

from src.runtime.harness_flags import harness_v2_injections, harness_v2_messages
from src.runtime.messages import (
    AionMessage,
    convert_to_llm,
    haystack_list_to_aion,
    injection_from_layer,
    layers_to_injections,
    transform_context,
)


@dataclass
class BuiltContext:
    messages: List[ChatMessage]
    aion_messages: List[AionMessage]


def build_llm_messages(
    stm_window: List[ChatMessage],
    *,
    user_text: str,
    inject_layers: Optional[List[dict]] = None,
    attachments_block: str = "",
) -> BuiltContext:
    """Assemble STM + structured injections + user message for the agent."""
    if not harness_v2_messages():
        msgs = list(stm_window)
        if inject_layers:
            prefix = "\n\n".join(
                str(x.get("text") or "") for x in inject_layers if x.get("text")
            ).strip()
            full_user = f"{prefix}\n\n{user_text}".strip() if prefix else user_text
        else:
            full_user = user_text
        if attachments_block.strip():
            full_user = f"{attachments_block.strip()}\n\n{full_user}"
        msgs.append(ChatMessage.from_user(full_user))
        return BuiltContext(messages=msgs, aion_messages=[])

    aion: List[AionMessage] = haystack_list_to_aion(stm_window)

    if harness_v2_injections() and inject_layers:
        aion.extend(layers_to_injections(inject_layers))
    elif inject_layers:
        # v2 messages but legacy injection concat as single injection block
        combined = "\n\n".join(
            str(x.get("text") or "") for x in inject_layers if x.get("text")
        ).strip()
        if combined:
            aion.append(injection_from_layer("hooks", combined))

    user_body = user_text
    if attachments_block.strip():
        user_body = f"{attachments_block.strip()}\n\n{user_body}"
    aion.append(AionMessage(role="user", content=user_body))

    aion = transform_context(aion)
    return BuiltContext(messages=convert_to_llm(aion), aion_messages=aion)


def refresh_agent_turn_context(
    agent,
    *,
    profile_name: str,
    user_id: str = "",
    user_lang: Optional[str] = None,
    agent_mode: Optional[str] = None,
) -> None:
    """prepareNextTurn: refresh system prompt on cached agent when possible."""
    try:
        from src.agent_profile import profile_manager

        profile = profile_manager.get_profile(profile_name)
        if profile is None:
            return
        prompt = profile.generate_system_prompt(user_id=user_id)
        if user_lang:
            from src.runtime.user_language import build_ui_language_prompt_section

            prompt += build_ui_language_prompt_section(user_lang)
        mode = (agent_mode or "chat").strip().lower()
        if mode == "plan":
            from src.runtime.plan_mode import build_plan_mode_system_prompt

            prompt += build_plan_mode_system_prompt()
        elif mode == "deep_research":
            from src.runtime.deep_research_mode import build_deep_research_system_prompt

            prompt += build_deep_research_system_prompt()
        if prompt and hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
    except Exception:
        pass
