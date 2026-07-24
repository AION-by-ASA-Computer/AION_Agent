"""Write Pi session config: models.json, settings.json, SYSTEM.md."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("aion.pi_session_config")


@dataclass(frozen=True)
class PiLlmConfig:
    base_url: str
    model_id: str
    api_key: str


def _is_qwen_vllm_model(model_id: str, base_url: str = "") -> bool:
    """Heuristic: local OpenAI-compatible Qwen served via vLLM."""
    m = (model_id or "").strip().lower()
    u = (base_url or "").strip().lower()
    if any(x in m for x in ("qwen", "aionq", "glm")):
        return True
    if any(x in u for x in ("localhost", "127.0.0.1", "192.168.", "10.", "172.")):
        return "qwen" in m or "/qwen" in u
    return False


def _normalize_openai_base_url(url: str) -> str:
    raw = (url or "").strip().rstrip("/")
    if not raw:
        return "http://127.0.0.1:8000/v1"
    if not raw.endswith("/v1"):
        if "/v1" not in raw:
            raw = f"{raw}/v1"
    return raw


async def resolve_pi_llm_config(
    llm_provider_name: Optional[str],
) -> PiLlmConfig:
    """Resolve OpenAI-compatible endpoint + model id for Pi (same rules as get_agent)."""
    from sqlalchemy import select

    from src.data.engine import get_async_session_maker
    from src.data.models import LlmProvider
    from src.runtime.credential_store import decrypt_value
    from src.runtime.llm_adapter import resolve_llm_endpoint

    api_key = (
        os.getenv("AION_API_KEY") or os.getenv("OPENAI_API_KEY") or "aion"
    ).strip()
    llm_url, llm_model = resolve_llm_endpoint()
    model_id = llm_model.split("/", 1)[-1] if "/" in (llm_model or "") else llm_model
    base_url = _normalize_openai_base_url(llm_url)

    slug = (llm_provider_name or "").strip()
    if not slug:
        return PiLlmConfig(base_url=base_url, model_id=model_id, api_key=api_key)

    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(LlmProvider).where(
                        LlmProvider.tenant_id == "default",
                        LlmProvider.slug == slug,
                    )
                )
            )
            .scalars()
            .first()
        )

    if not row or not row.enabled:
        if row and not row.enabled:
            logger.warning(
                "Pi LLM provider %s disabled, falling back to env endpoint",
                slug,
            )
        return PiLlmConfig(base_url=base_url, model_id=model_id, api_key=api_key)

    base_url = _normalize_openai_base_url(row.api_base_url)
    model_id = (row.model_name or "").strip()
    if not model_id:
        model_id = llm_model.split("/", 1)[-1] if "/" in (llm_model or "") else llm_model
    if row.api_key_encrypted:
        try:
            api_key = decrypt_value(row.api_key_encrypted)
        except Exception as exc:
            logger.warning("Pi LLM provider key decrypt failed: %s", exc)

    return PiLlmConfig(base_url=base_url, model_id=model_id, api_key=api_key)


async def write_pi_models_json(
    agent_dir: Path,
    profile: Any,
    llm_provider_name: Optional[str],
) -> PiLlmConfig:
    cfg = await resolve_pi_llm_config(llm_provider_name)
    try:
        max_tokens = int(os.getenv("AION_CHAT_MAX_TOKENS", "16384"))
    except ValueError:
        max_tokens = 16384
    try:
        context_window = int(os.getenv("AION_CONTEXT_WINDOW", "131072"))
    except ValueError:
        context_window = 131072
    compat: dict[str, Any] = {
        "supportsDeveloperRole": False,
        "supportsReasoningEffort": False,
    }
    model_entry: dict[str, Any] = {
        "id": cfg.model_id,
        "name": cfg.model_id,
        "input": ["text"],
        "contextWindow": context_window,
        "maxTokens": max_tokens,
    }
    if _is_qwen_vllm_model(cfg.model_id, cfg.base_url):
        # Mirror Haystack vLLM/Qwen: chat_template_kwargs + separate reasoning stream.
        compat["supportsStrictMode"] = False
        compat["thinkingFormat"] = "qwen-chat-template"
        model_entry["reasoning"] = True
        model_entry["thinkingLevelMap"] = {
            "off": None,
            "low": "low",
            "medium": "medium",
            "high": "high",
        }

    payload = {
        "providers": {
            "aion": {
                "baseUrl": cfg.base_url,
                "api": "openai-completions",
                "apiKey": cfg.api_key,
                "compat": compat,
                "models": [model_entry],
            }
        }
    }
    (agent_dir / "models.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    return cfg


def write_pi_settings_json(agent_dir: Path, *, default_model: Optional[str] = None) -> None:
    reserve = int(os.getenv("AION_PI_COMPACTION_RESERVE_TOKENS", "16384"))
    keep = int(os.getenv("AION_PI_COMPACTION_KEEP_RECENT_TOKENS", "20000"))
    payload = {
        "compaction": {
            "enabled": True,
            "reserveTokens": reserve,
            "keepRecentTokens": keep,
        },
        "defaultProvider": "aion",
        "defaultModel": default_model,
    }
    (agent_dir / "settings.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def write_system_prompt(
    agent_dir: Path,
    profile: Any,
    *,
    extra: str = "",
    llm_cfg: Optional[PiLlmConfig] = None,
) -> None:
    base = ""
    provider = "vllm" if llm_cfg and _is_qwen_vllm_model(llm_cfg.model_id, llm_cfg.base_url) else ""
    model_id = llm_cfg.model_id if llm_cfg else ""
    try:
        base = (
            profile.generate_system_prompt(provider=provider, model_id=model_id) or ""
        )
    except Exception as exc:
        logger.warning("generate_system_prompt failed: %s", exc)
    from src.runtime.long_run_mode import build_long_run_system_prompt

    text = (base + build_long_run_system_prompt() + (extra or "")).strip()
    (agent_dir / "SYSTEM.md").write_text(text + "\n", encoding="utf-8")


async def prepare_pi_session_files(
    session_id: str,
    profile: Any,
    *,
    llm_provider_name: Optional[str] = None,
    extra_system: str = "",
) -> tuple[Path, PiLlmConfig]:
    from src.runtime.long_run_mode import pi_session_dir
    from src.runtime.pi_runtime.skill_sync import sync_profile_skills

    agent_dir = Path(pi_session_dir(session_id))
    agent_dir.mkdir(parents=True, exist_ok=True)
    llm_cfg = await write_pi_models_json(agent_dir, profile, llm_provider_name)
    write_pi_settings_json(agent_dir, default_model=llm_cfg.model_id)
    write_system_prompt(agent_dir, profile, extra=extra_system, llm_cfg=llm_cfg)
    sync_profile_skills(session_id, profile)
    return agent_dir, llm_cfg
