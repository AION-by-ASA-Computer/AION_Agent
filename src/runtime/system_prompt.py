"""
OpenCode-style model prompt fragments and skills catalog assembly.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from src.skill_registry import skill_registry


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _prompts_dir() -> Path:
    raw = (os.getenv("AION_PROMPTS_DIR") or "config_std/prompts").strip()
    p = Path(raw)
    return p if p.is_absolute() else _repo_root() / p


def _tool_descriptions_dir() -> Path:
    raw = (os.getenv("AION_TOOL_DESCRIPTIONS_DIR") or "config_std/tool_descriptions").strip()
    p = Path(raw)
    return p if p.is_absolute() else _repo_root() / p


def _read_fragment(name: str) -> str:
    path = _prompts_dir() / name
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_tool_description(tool_name: str) -> str:
    """Optional extended description for MCP tool (basename without server prefix)."""
    base = (tool_name or "").split("-")[-1].strip().lower()
    path = _tool_descriptions_dir() / f"{base}.txt"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _normalize_model_id(model_id: str) -> str:
    return (model_id or "").strip().lower()


def _is_gpt_patch_model(model_id: str) -> bool:
    m = _normalize_model_id(model_id)
    if not m.startswith("gpt-"):
        return False
    if m.startswith("gpt-4") or "oss" in m:
        return False
    return True


def _is_anthropic_model(provider: str, model_id: str) -> bool:
    p = (provider or "").strip().lower()
    m = _normalize_model_id(model_id)
    return p in ("anthropic", "claude") or m.startswith("claude")


def _is_local_vllm(provider: str, model_id: str) -> bool:
    p = (provider or "").strip().lower()
    m = _normalize_model_id(model_id)
    if p in ("vllm", "openai_compatible", "local"):
        return True
    return any(x in m for x in ("qwen", "llama", "mistral", "deepseek", "glm"))


def select_model_prompt(
    provider: str = "",
    model_id: str = "",
) -> List[str]:
    """
    Return ordered prompt fragments for the active model.
    Always includes default.txt; adds provider-specific overlay when matched.
    """
    if os.getenv("AION_MODEL_PROMPT_FRAGMENTS", "1").strip().lower() in ("0", "false", "no"):
        return []

    out: List[str] = []
    default = _read_fragment("default.txt")
    if default:
        out.append(default)

    if _is_gpt_patch_model(model_id):
        frag = _read_fragment("gpt.txt")
        if frag:
            out.append(frag)
    elif _is_anthropic_model(provider, model_id):
        frag = _read_fragment("anthropic.txt")
        if frag:
            out.append(frag)
    elif _is_local_vllm(provider, model_id):
        frag = _read_fragment("qwen_vllm.txt")
        if frag:
            out.append(frag)

    return out


def build_skills_catalog_xml(allowed_names: Optional[List[str]] = None) -> str:
    """OpenCode-style <available_skills> block for index-mode profiles."""
    summaries = skill_registry.list_summaries(allowed_names=allowed_names)
    if not summaries:
        return ""
    lines = ["<available_skills>"]
    for s in summaries:
        name = _xml_escape(str(s.get("name") or ""))
        desc = _xml_escape(str(s.get("description") or ""))
        lines.append(f"  <skill><name>{name}</name><description>{desc}</description></skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def assemble_model_prompt_section(
    provider: str = "",
    model_id: str = "",
) -> str:
    parts = select_model_prompt(provider=provider, model_id=model_id)
    if not parts:
        return ""
    return "## Agent behavior (model-specific)\n\n" + "\n\n".join(parts)
