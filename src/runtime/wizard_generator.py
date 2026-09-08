"""AI Wizard Generator per la creazione guidata di Profili ed il binding di Skill/MCP."""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import frontmatter
from haystack.dataclasses import ChatMessage
from haystack.utils import Secret

from src.agent_profile import profile_manager
from src.haystack_chat import chat_message_text
from src.mcp_manager import mcp_manager
from src.runtime.llm_adapter import resolve_llm_credentials
from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper
from src.skill_registry import skill_registry

logger = logging.getLogger("aion.runtime.wizard_generator")

MANDATORY_SKILLS = ["core_protocol", "artifact_protocol"]
MANDATORY_MCPS = ["session_sandbox", "skills_hub"]


def _normalize_skill_result(
    raw: Dict[str, Any], current_skill: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Parsing e normalizzazione del risultato LLM per le Skill con python-frontmatter."""
    raw_name = (
        str(
            raw.get("name")
            or (current_skill and current_skill.get("name"))
            or "custom_skill"
        )
        .strip()
        .lower()
    )
    name = re.sub(r"[^a-z0-9_]", "_", raw_name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "custom_skill"

    raw_content = str(
        raw.get("content") or (current_skill and current_skill.get("content")) or ""
    )

    post_meta: Dict[str, Any] = {}
    post_body: str = raw_content
    try:
        if raw_content.strip():
            post = frontmatter.loads(raw_content)
            post_meta = dict(post.metadata) if post.metadata else {}
            post_body = post.content or ""
    except Exception as exc:
        logger.warning("Frontmatter parsing failed: %s", exc)

    desc = str(
        raw.get("description")
        or post_meta.get("description")
        or (current_skill and current_skill.get("description"))
        or ""
    ).strip()

    raw_tags = (
        raw.get("tags")
        or post_meta.get("tags")
        or (current_skill and current_skill.get("tags"))
        or []
    )
    if isinstance(raw_tags, str):
        tags = [t.strip().lower() for t in raw_tags.split(",") if t.strip()]
    elif isinstance(raw_tags, list):
        tags = [str(t).strip().lower() for t in raw_tags if isinstance(t, (str, int))]
    else:
        tags = []

    if not tags:
        tags = ["custom"]

    status = str(
        raw.get("status")
        or post_meta.get("status")
        or (current_skill and current_skill.get("status"))
        or "draft"
    ).strip()

    if not post_body.strip():
        post_body = (
            f"# {name.replace('_', ' ').title()}\n\nDescribe the skill protocol here..."
        )

    return {
        "name": name,
        "description": desc,
        "tags": tags,
        "status": status,
        "content": post_body.strip(),
    }


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text)
    if m:
        return m.group(1).strip()
    return text


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text or not str(text).strip():
        return None
    raw = _strip_json_fence(str(text).strip())
    if not raw:
        return None

    try:
        out = json.loads(raw)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    if start >= 0:
        candidate = raw[start:]
        depth = 0
        for i, ch in enumerate(candidate):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        out = json.loads(candidate[: i + 1])
                        if isinstance(out, dict):
                            return out
                    except json.JSONDecodeError:
                        break

        for suffix in ['"}', '"\n}', '"]}', '"\n  }\n}', '"}', "}"]:
            try:
                out = json.loads(candidate + suffix)
                if isinstance(out, dict):
                    return out
            except json.JSONDecodeError:
                continue

        name_m = re.search(r'"name"\s*:\s*"([^"]+)"', candidate)
        slug_m = re.search(r'"slug"\s*:\s*"([^"]+)"', candidate)
        desc_m = re.search(r'"description"\s*:\s*"([^"]+)"', candidate)
        instr_m = re.search(
            r'"instructions"\s*:\s*"([\s\S]+?)"(?:\s*,\s*"|\s*})', candidate
        )

        if name_m or slug_m or desc_m:
            return {
                "name": name_m.group(1) if name_m else "Custom Agent",
                "slug": slug_m.group(1) if slug_m else "custom_agent",
                "description": desc_m.group(1)
                if desc_m
                else "Generated agent profile.",
                "instructions": instr_m.group(1)
                if instr_m
                else "# Role: Custom Agent\n\nProvide helpful assistance in English.",
                "skills": MANDATORY_SKILLS,
                "mcp_servers": MANDATORY_MCPS,
            }

    return None


def _call_llm_for_json(
    system_prompt: str,
    user_prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
    timeout: float = 90.0,
) -> Dict[str, Any]:
    base, model, token = resolve_llm_credentials()
    max_tokens = int(os.getenv("AION_WIZARD_MAX_TOKENS", "8192"))

    gen_kwargs = {
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }

    api_key_secret = Secret.from_token(token) if token else None
    generator = LiteLLMChatGeneratorWrapper(
        model=model,
        api_base_url=base,
        api_key=api_key_secret,
        timeout=timeout,
        generation_kwargs=gen_kwargs,
    )

    messages = [ChatMessage.from_system(system_prompt)]
    if history:
        for item in history:
            role = item.get("role", "user")
            text = item.get("content", "")
            if role == "assistant":
                messages.append(ChatMessage.from_assistant(text))
            elif role == "user":
                messages.append(ChatMessage.from_user(text))

    messages.append(ChatMessage.from_user(user_prompt))

    res = generator.run(messages=messages)
    if not res or "replies" not in res or not res["replies"]:
        raise ValueError("Risposta vuota dal provider LLM")

    raw_reply = res["replies"][0]
    if raw_reply is None:
        raise ValueError("Risposta nulla ricevuta dal provider LLM")

    if isinstance(raw_reply, ChatMessage):
        content = chat_message_text(raw_reply)
    else:
        content = str(getattr(raw_reply, "text", raw_reply) or "")

    if not content or not str(content).strip():
        raise ValueError("Contenuto vuoto nella risposta LLM")

    parsed = _extract_json_object(str(content))
    if not parsed:
        safe_snippet = str(content)[:200] if content else "None"
        raise ValueError(
            f"Impossibile interpretare il JSON dalla risposta LLM: {safe_snippet}"
        )
    return parsed


async def suggest_profile_enhancements(
    prompt: str, history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """Genera suggerimenti interattivi e domande di affinamento per il profilo utente."""
    profile_manager.load_all_if_stale()
    wizard_profile = profile_manager.get_profile("aion_wizard_creator")
    base_instructions = (
        wizard_profile.instructions
        if wizard_profile
        else "You are the AI Profile Creator for AION Agent."
    )

    system_prompt = (
        f"{base_instructions}\n\n"
        "TASK: Analyze the user's agent request and provide helpful suggestions or enhancement questions.\n"
        "Output MUST be a single JSON object with:\n"
        "{\n"
        '  "summary": "Short analysis of what the agent will do...",\n'
        '  "suggestions": [\n'
        '    {"id": "memory", "label": "🧠 Memory & Context Recall", "description": "Enable long-term memory for past user conversations."},\n'
        '    {"id": "email", "label": "📧 Email Reading (IMAP)", "description": "Allow reading and responding to customer emails."},\n'
        '    {"id": "web_research", "label": "🌐 Web Research", "description": "Allow deep web browsing and online search."},\n'
        '    {"id": "database", "label": "🗄️ SQL Database Access", "description": "Allow schema inspection and SQL queries."}\n'
        "  ]\n"
        "}"
    )

    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(
        None, _call_llm_for_json, system_prompt, prompt, history
    )
    return raw


async def generate_profile_wizard(
    prompt: str, history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """Genera un profilo agente strictly in ENGLISH basandosi su aion_wizard_creator ed i cataloghi reali."""
    profile_manager.load_all_if_stale()
    wizard_profile = profile_manager.get_profile("aion_wizard_creator")
    base_instructions = (
        wizard_profile.instructions
        if wizard_profile
        else "You are the AI Profile Creator for AION Agent."
    )

    skill_registry.reload_if_stale()
    available_skills = skill_registry.list_summaries()
    skills_context = [
        {
            "name": s["name"],
            "description": s.get("description", ""),
            "tags": s.get("tags", []),
        }
        for s in available_skills
    ]

    mcp_registry = getattr(mcp_manager, "_registry", {}) or {}
    mcps_context = [
        {
            "name": name,
            "description": cfg.get("description", "") if isinstance(cfg, dict) else "",
            "type": cfg.get("type", "stdio") if isinstance(cfg, dict) else "stdio",
        }
        for name, cfg in mcp_registry.items()
    ]

    system_prompt = (
        f"{base_instructions}\n\n"
        "--- SYSTEM CATALOG CONTEXT ---\n"
        "AVAILABLE SKILLS CATALOG:\n"
        f"{json.dumps(skills_context, indent=2, ensure_ascii=False)}\n\n"
        "AVAILABLE MCP SERVERS CATALOG:\n"
        f"{json.dumps(mcps_context, indent=2, ensure_ascii=False)}\n\n"
        "STRICT MANDATORY RULES:\n"
        "1. ALL OUTPUT TEXT ('name', 'description', 'instructions') MUST BE WRITTEN IN ENGLISH.\n"
        "2. NAMING SCHEMA & FORBIDDEN CHARACTERS:\n"
        "   - Use ONLY letters (a-z, A-Z), numbers (0-9), spaces, and underscores in 'name'.\n"
        "   - STRICTLY FORBIDDEN CHARACTERS: Never use special symbols like '&', '/', '\\', '(', ')', '-', '+', ':', ',', '#', '@', '!', '?'.\n"
        "   - Always spell out conjunctions (e.g., use 'and' instead of '&'). Example: 'Document Analyst and Researcher' instead of 'Document Analyst & Researcher'.\n"
        "   - The 'slug' MUST strictly be lowercase snake_case containing ONLY [a-z0-9_] (e.g., 'document_analyst_and_researcher').\n"
        f"3. MANDATORY SKILLS TO INCLUDE: {json.dumps(MANDATORY_SKILLS)}\n"
        f"4. MANDATORY MCP SERVERS TO INCLUDE: {json.dumps(MANDATORY_MCPS)}\n"
        "5. Choose additional relevant skills and MCP servers ONLY from the provided catalogs.\n"
        "6. INSTRUCTION CONCISENESS & FLEXIBILITY:\n"
        "   - Keep 'instructions' clear, well-structured, and concise by default (avoid generic fluff, filler text, or redundant preamble).\n"
        "   - However, if the user explicitly requests a complex profile with extensive rules, detailed domain constraints, or multi-step protocols, satisfy all requirements fully without omitting requested details.\n"
        "7. Respond EXCLUSIVELY with a JSON object with the keys:\n"
        "{\n"
        '  "name": "Readable Agent Name in English",\n'
        '  "slug": "agent_name_snake_case",\n'
        '  "description": "Short role description in English",\n'
        '  "instructions": "# Role: ...\\n\\nSystem instructions in English...",\n'
        '  "skills": ["core_protocol", "artifact_protocol", ...],\n'
        '  "mcp_servers": ["session_sandbox", "skills_hub", ...]\n'
        "}"
    )

    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(
        None, _call_llm_for_json, system_prompt, prompt, history
    )

    existing_skills = set(skill_registry.get_all_names())
    existing_mcps = set(mcp_registry.keys())

    selected_skills = [
        s for s in raw.get("skills", []) if isinstance(s, str) and s in existing_skills
    ]
    # Enforce MANDATORY SKILLS
    for mand_s in MANDATORY_SKILLS:
        if mand_s in existing_skills and mand_s not in selected_skills:
            selected_skills.insert(0, mand_s)

    selected_mcps = [
        m
        for m in raw.get("mcp_servers", [])
        if isinstance(m, str) and m in existing_mcps
    ]
    # Enforce MANDATORY MCPs
    for mand_m in MANDATORY_MCPS:
        if mand_m in existing_mcps and mand_m not in selected_mcps:
            selected_mcps.insert(0, mand_m)

    raw_slug = str(raw.get("slug") or raw.get("name") or "custom_agent").strip().lower()
    slug = re.sub(r"[^a-z0-9_]", "_", raw_slug)

    return {
        "name": str(raw.get("name") or "Custom Agent"),
        "slug": slug,
        "description": str(raw.get("description") or ""),
        "instructions": str(
            raw.get("instructions")
            or "# Role: Custom Agent\n\nProvide helpful assistance in English."
        ),
        "skills": selected_skills,
        "mcp_servers": selected_mcps,
    }


async def refine_profile_wizard(
    prompt: str, current_profile: Dict[str, Any]
) -> Dict[str, Any]:
    """Rifinisce ed aggiorna in-place un profilo agente esistente leggendo lo stato corrente del form."""
    profile_manager.load_all_if_stale()
    wizard_profile = profile_manager.get_profile("aion_wizard_creator")
    base_instructions = (
        wizard_profile.instructions
        if wizard_profile
        else "You are the AI Profile Creator for AION Agent."
    )

    skill_registry.reload_if_stale()
    available_skills = skill_registry.list_summaries()
    skills_context = [
        {
            "name": s["name"],
            "description": s.get("description", ""),
            "tags": s.get("tags", []),
        }
        for s in available_skills
    ]

    mcp_registry = getattr(mcp_manager, "_registry", {}) or {}
    mcps_context = [
        {
            "name": name,
            "description": cfg.get("description", "") if isinstance(cfg, dict) else "",
            "type": cfg.get("type", "stdio") if isinstance(cfg, dict) else "stdio",
        }
        for name, cfg in mcp_registry.items()
    ]

    system_prompt = (
        f"{base_instructions}\n\n"
        "--- CURRENT PROFILE BEING EDITED ---\n"
        f"{json.dumps(current_profile, indent=2, ensure_ascii=False)}\n\n"
        "--- SYSTEM CATALOG CONTEXT ---\n"
        "AVAILABLE SKILLS CATALOG:\n"
        f"{json.dumps(skills_context, indent=2, ensure_ascii=False)}\n\n"
        "AVAILABLE MCP SERVERS CATALOG:\n"
        f"{json.dumps(mcps_context, indent=2, ensure_ascii=False)}\n\n"
        "TASK:\n"
        "Refine and update the current profile based on the IT Manager's request:\n"
        f'USER REQUEST: "{prompt}"\n\n'
        "STRICT MANDATORY RULES:\n"
        "1. ALL OUTPUT TEXT ('name', 'description', 'instructions') MUST BE WRITTEN IN ENGLISH.\n"
        "2. NAMING SCHEMA & FORBIDDEN CHARACTERS:\n"
        "   - Use ONLY letters (a-z, A-Z), numbers (0-9), spaces, and underscores in 'name'.\n"
        "   - STRICTLY FORBIDDEN CHARACTERS: Never use special symbols like '&', '/', '\\', '(', ')', '-', '+', ':', ',', '#', '@', '!', '?'.\n"
        "   - Always spell out conjunctions (e.g., use 'and' instead of '&'). Example: 'Document Analyst and Researcher' instead of 'Document Analyst & Researcher'.\n"
        "   - The 'slug' MUST strictly be lowercase snake_case containing ONLY [a-z0-9_] (e.g., 'document_analyst_and_researcher').\n"
        "3. Retain existing skills and MCPs unless specifically asked to remove them.\n"
        f"4. MANDATORY SKILLS TO ALWAYS INCLUDE: {json.dumps(MANDATORY_SKILLS)}\n"
        f"5. MANDATORY MCP SERVERS TO ALWAYS INCLUDE: {json.dumps(MANDATORY_MCPS)}\n"
        "6. INSTRUCTION CONCISENESS & FLEXIBILITY:\n"
        "   - Keep 'instructions' clear, well-structured, and concise by default (avoid generic fluff, filler text, or redundant preamble).\n"
        "   - However, if the user explicitly requests a complex profile with extensive rules, detailed domain constraints, or multi-step protocols, satisfy all requirements fully without omitting requested details.\n"
        "7. Respond EXCLUSIVELY with a JSON object:\n"
        "{\n"
        '  "name": "Updated Agent Name in English",\n'
        '  "slug": "existing_or_new_snake_case_slug",\n'
        '  "description": "Updated short role description in English",\n'
        '  "instructions": "# Role: ...\\n\\nUpdated system instructions in English...",\n'
        '  "skills": ["core_protocol", "artifact_protocol", ...],\n'
        '  "mcp_servers": ["session_sandbox", "skills_hub", ...]\n'
        "}"
    )

    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(None, _call_llm_for_json, system_prompt, prompt)

    existing_skills = set(skill_registry.get_all_names())
    existing_mcps = set(mcp_registry.keys())

    selected_skills = [
        s for s in raw.get("skills", []) if isinstance(s, str) and s in existing_skills
    ]
    for mand_s in MANDATORY_SKILLS:
        if mand_s in existing_skills and mand_s not in selected_skills:
            selected_skills.insert(0, mand_s)

    selected_mcps = [
        m
        for m in raw.get("mcp_servers", [])
        if isinstance(m, str) and m in existing_mcps
    ]
    for mand_m in MANDATORY_MCPS:
        if mand_m in existing_mcps and mand_m not in selected_mcps:
            selected_mcps.insert(0, mand_m)

    raw_slug = (
        str(
            raw.get("slug")
            or current_profile.get("slug")
            or current_profile.get("name")
            or "custom_agent"
        )
        .strip()
        .lower()
    )
    slug = re.sub(r"[^a-z0-9_]", "_", raw_slug)

    return {
        "name": str(raw.get("name") or current_profile.get("name") or "Custom Agent"),
        "slug": slug,
        "description": str(
            raw.get("description") or current_profile.get("description") or ""
        ),
        "instructions": str(
            raw.get("instructions") or current_profile.get("instructions") or ""
        ),
        "skills": selected_skills,
        "mcp_servers": selected_mcps,
    }


async def generate_skill_wizard(
    prompt: str, history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """Genera una Skill Markdown con frontmatter YAML strictly in ENGLISH."""
    profile_manager.load_all_if_stale()
    wizard_profile = profile_manager.get_profile("aion_wizard_creator")
    base_instructions = (
        wizard_profile.instructions
        if wizard_profile
        else "You are the AI Skill Creator for AION Agent."
    )

    skill_registry.reload_if_stale()
    available_skills = skill_registry.list_summaries()
    skills_context = [s["name"] for s in available_skills]

    system_prompt = (
        f"{base_instructions}\n\n"
        f"EXISTING SKILLS IN SYSTEM: {json.dumps(skills_context)}\n\n"
        "STRICT MANDATORY RULES:\n"
        "1. ALL OUTPUT CONTENT MUST BE WRITTEN IN ENGLISH.\n"
        "2. NAMING SCHEMA & FORBIDDEN CHARACTERS:\n"
        "   - The 'name' MUST strictly be lowercase snake_case containing ONLY [a-z0-9_] (e.g., 'invoice_reconciliation').\n"
        "   - NEVER use special symbols like '&', '/', '\\', '(', ')', '-', '+', ':', ',', '#', '@', '!', '?'.\n"
        "3. Write the procedural Markdown protocol guidelines inside the 'content' field.\n"
        "4. Respond EXCLUSIVELY with a JSON object containing the keys:\n"
        "{\n"
        '  "name": "skill_name_snake_case",\n'
        '  "description": "Short description of the skill purpose in English",\n'
        '  "tags": ["tag1", "tag2"],\n'
        '  "status": "draft",\n'
        '  "content": "# Skill Title in English\\n\\n## Objective\\n...\\n\\n## Step-by-Step Instructions..."\n'
        "}"
    )

    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(
        None, _call_llm_for_json, system_prompt, prompt, history
    )
    return _normalize_skill_result(raw)


async def refine_skill_wizard(
    prompt: str, current_skill: Dict[str, Any]
) -> Dict[str, Any]:
    """Rifinisce ed aggiorna in-place una Skill esistente leggendo lo stato corrente del form."""
    profile_manager.load_all_if_stale()
    wizard_profile = profile_manager.get_profile("aion_wizard_creator")
    base_instructions = (
        wizard_profile.instructions
        if wizard_profile
        else "You are the AI Skill Creator for AION Agent."
    )

    system_prompt = (
        f"{base_instructions}\n\n"
        "--- CURRENT SKILL BEING EDITED ---\n"
        f"{json.dumps(current_skill, indent=2, ensure_ascii=False)}\n\n"
        "TASK:\n"
        "Refine and update the current Skill protocol based on the IT Manager's request:\n"
        f'USER REQUEST: "{prompt}"\n\n'
        "STRICT MANDATORY RULES:\n"
        "1. ALL OUTPUT CONTENT MUST BE WRITTEN IN ENGLISH.\n"
        "2. NAMING SCHEMA & FORBIDDEN CHARACTERS:\n"
        "   - The 'name' MUST strictly be lowercase snake_case containing ONLY [a-z0-9_] (e.g., 'invoice_reconciliation').\n"
        "   - NEVER use special symbols like '&', '/', '\\', '(', ')', '-', '+', ':', ',', '#', '@', '!', '?'.\n"
        "3. Write the procedural Markdown protocol guidelines inside the 'content' field.\n"
        "4. Respond EXCLUSIVELY with a JSON object containing the keys:\n"
        "{\n"
        '  "name": "skill_name_snake_case",\n'
        '  "description": "Short updated description of the skill in English",\n'
        '  "tags": ["tag1", "tag2"],\n'
        '  "status": "draft",\n'
        '  "content": "# Skill Title in English\\n\\n## Objective\\n...\\n\\n## Updated Instructions..."\n'
        "}"
    )

    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(None, _call_llm_for_json, system_prompt, prompt)
    return _normalize_skill_result(raw, current_skill)
