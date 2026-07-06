"""MCP: ricerca e lettura on-demand delle skill (Hermes FASE A)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from fastmcp import FastMCP

from src.skill_registry import skill_registry

import yaml

class FlowList(list):
    pass

def flow_list_representer(dumper, data):
    return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)

yaml.add_representer(FlowList, flow_list_representer, Dumper=yaml.SafeDumper)
try:
    from yaml import CSafeDumper
    yaml.add_representer(FlowList, flow_list_representer, Dumper=CSafeDumper)
except ImportError:
    pass

logger = logging.getLogger("aion.skills_hub")
mcp = FastMCP("AION Skills Hub")


def _profile_allowed_skill_names() -> list[str] | None:
    """Limit search to skills on the active profile when slug is set on the MCP subprocess."""
    slug = (os.getenv("AION_CURRENT_PROFILE_SLUG") or "").strip()
    session_id = os.getenv("AION_CHAT_SESSION_ID")
    if session_id:
        import sqlite3
        db_path = "data/aion.db"
        db_url = os.getenv("AION_DB_URL", "")
        if "sqlite" in db_url:
            parts = db_url.split(":///")
            if len(parts) == 2:
                db_path = parts[1]
        try:
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
            abs_db_path = os.path.join(repo_root, db_path)
            if os.path.exists(abs_db_path):
                with sqlite3.connect(abs_db_path, timeout=5) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT profile_slug FROM conversations WHERE id = ?", (session_id,))
                    row = cursor.fetchone()
                    if row and row[0]:
                        slug = row[0]
        except Exception as e:
            logger.warning("Failed to query profile_slug from database for session %s: %s", session_id, e)

    if not slug:
        return None
    try:
        from src.agent_profile import profile_manager

        profile_manager.load_all()
        prof = profile_manager.get_profile(slug)
        if prof:
            return list(prof.skills or [])
    except Exception:
        pass
    return None


def _skill_allowed_for_profile(name: str) -> bool:
    """Enforce profile.skills allowlist on skill_view / skill_list (search already filters)."""
    slug = (name or "").strip()
    if os.getenv("AION_SKILL_VIEW_ENFORCE_PROFILE", "1").strip().lower() in (
        "0",
        "false",
        "no",
    ):
        return True
    allowed = _profile_allowed_skill_names()
    if allowed is None:
        return True
    return slug in allowed or slug == "core_protocol"



_OFFICE_SLUGS = ("docx", "pdf", "xlsx", "pptx")


def _office_slug_hits(query: str, allowed: list[str] | None) -> list[dict]:
    q = (query or "").lower()
    triggers = {
        "docx": ("docx", "word", "document"),
        "pdf": ("pdf",),
        "xlsx": ("xlsx", "excel", "spreadsheet"),
        "pptx": ("pptx", "powerpoint", "presentation"),
    }
    hits: list[dict] = []
    for slug, keys in triggers.items():
        if allowed is not None and slug not in allowed:
            continue
        if not any(k in q for k in keys):
            continue
        meta = skill_registry.get_meta(slug)
        if meta and skill_registry.get_skill_full(slug):
            hits.append(dict(meta))
    return hits


@mcp.tool()
def skill_search(query: str, top_k: int = 5) -> str:
    """Search skills by name, tag, or description (limited to active profile skills when available)."""
    allowed = _profile_allowed_skill_names()
    results = skill_registry.search(query, top_k=top_k, allowed_names=allowed)
    if not results:
        results = _office_slug_hits(query, allowed)
    if not results and allowed:
        qlow = (query or "").lower()
        if any(
            tok in qlow
            for tok in (
                "doc",
                "word",
                "corso",
                "document",
                "ml ",
                "machine learning",
                "manuale",
            )
        ):
            for slug in _OFFICE_SLUGS:
                if slug not in allowed:
                    continue
                meta = skill_registry.get_meta(slug)
                if meta and skill_registry.get_skill_full(slug):
                    results.append(dict(meta))
    if not results:
        hint = ""
        if allowed:
            office = [s for s in _OFFICE_SLUGS if s in allowed and skill_registry.get_skill_full(s)]
            if office:
                hint = f" Try skill_view directly: {', '.join(office)}."
        return f"No matching skills.{hint}"
    lines = [f"Found {len(results)} skills:"]
    for m in results:
        tags = ",".join(m.get("tags") or [])
        lines.append(f"- {m['name']}: {m.get('description', '')} [tags: {tags}]")
    lines.append("Use skill_view(name) for the full skill body.")
    out = "\n".join(lines)
    sid = (os.getenv("AION_CHAT_SESSION_ID") or "").strip()
    if sid and results:
        office_hits = [m["name"] for m in results if m.get("name") in {"docx", "pdf", "xlsx", "pptx"}]
        if office_hits:
            try:
                from src.tools.skill_materialize import materialize_skill_scripts

                for slug in office_hits[:2]:
                    materialize_skill_scripts(sid, slug)
            except Exception as e:
                logger.warning("skill_search materialize failed: %s", e)
                out += (
                    f"\n\n**AION:** script materialization failed ({e}); "
                    "usa `skill_view(\"docx\")` prima di `sandbox_exec_allowlisted`."
                )
            else:
                out += (
                    f"\n\n**AION:** office scripts pre-loaded in session for: "
                    f"{', '.join(office_hits[:2])}."
                )
    return out


@mcp.tool()
def skill_view(name: str, materialize: bool = True) -> str:
    """Returns the full markdown of a skill.

    Con ``materialize=True`` (default), copia ``scripts/`` del pacchetto skill nella
    current session (``AION_CHAT_SESSION_ID``) per ``sandbox_exec_allowlisted``.
    """
    slug = (name or "").strip()
    if not _skill_allowed_for_profile(slug):
        allowed = _profile_allowed_skill_names() or []
        prof = (os.getenv("AION_CURRENT_PROFILE_SLUG") or "").strip() or "?"
        return (
            f"Skill '{slug}' is not enabled in the active profile `{prof}`. "
            f"Allowed skills: {', '.join(allowed) or '(none)'}. "
            "For DB navigation use `mempalace_search` / chat-ui project drawer, "
            "not `skill_view` on skills removed from the profile."
        )
    body = skill_registry.get_skill_full(slug)
    if not body:
        return f"Skill '{slug}' not found."
    try:
        from src.learning.skill_view_metrics import record_skill_view

        uid = (os.getenv("AION_CURRENT_USER_ID") or os.getenv("USER_ID") or "default").strip()
        record_skill_view(slug, uid)
    except Exception:
        pass

    sid = (os.getenv("AION_CHAT_SESSION_ID") or "").strip()
    if sid:
        try:
            from src.tools.skill_materialize import record_skill_viewed
            record_skill_viewed(sid, slug)
        except Exception as e:
            logger.warning("Failed to record skill viewed for %s: %s", slug, e)

    if not materialize:
        return body
    if not sid:
        return body + "\n\n---\n**AION skill assets:** session id missing; scripts not materialized."
    try:
        from src.tools.skill_materialize import (
            format_materialize_footer,
            materialize_skill_scripts,
        )

        result = materialize_skill_scripts(sid, name)
        return body + format_materialize_footer(result, name)
    except Exception as e:
        logger.warning("skill materialize failed slug=%s: %s", name, e)
        return (
            body
            + f"\n\n---\n**AION skill assets:** materialization failed: {e}"
        )


@mcp.tool()
def skill_list() -> str:
    """List all skills (name and description)."""
    summaries = skill_registry.list_summaries()
    allowed = _profile_allowed_skill_names()
    if allowed is not None:
        allow_set = set(allowed)
        allow_set.add("core_protocol")
        summaries = [s for s in summaries if s.get("name") in allow_set]
    if not summaries:
        return "No skills loaded for this profile."
    return "\n".join(f"- {s['name']}: {s.get('description', '')}" for s in summaries)


@mcp.tool()
def skill_save(
    name: str,
    description: str,
    content: str,
    tags: list[str] = [],
    category: str = "curated",
) -> str:
    """Create or update an AION skill with YAML frontmatter.
    
    name: lo slug kebab-case della skill (es. 'clickup-update-task')
    description: short description for the index (progressive disclosure)
    content: skill Markdown body (detailed instructions)
    tags: tags useful for search (es. ['clickup', 'tasks'])
    category: 'curated' (salva in config/skills/ e config_std/skills/ per la permanenza) o 'generated' (in data/skills/generated/)
    """
    import os
    enabled = os.getenv("AION_SKILL_WRITE_ENABLED", "1").lower() in ("1", "true", "yes", "on")
    if not enabled:
        return "Error: skill write/delete (AION_SKILL_WRITE_ENABLED) is disabled for this MCP server."

    import frontmatter
    from pathlib import Path
    import re

    # Normalizza slug name a kebab-case
    slug = re.sub(r"[^a-z0-9-]+", "", name.lower().replace("_", "-").strip())
    if not slug:
        return "Error: invalid skill name."

    # Determine the relative path if the skill already exists in the registry
    existing_path = skill_registry.get_skill_path(slug)
    rel_path = None
    if existing_path:
        existing_path = Path(existing_path)
        for base_dir in (skill_registry.curated_dir, skill_registry.curated_fallback_dir, skill_registry.generated_dir):
            try:
                rel_path = existing_path.relative_to(base_dir)
                break
            except ValueError:
                continue

    if category == "generated":
        target_dirs = [skill_registry.generated_dir]
    else:
        # Default: salva in config/skills/ E config_std/skills/ per la permanenza
        target_dirs = [skill_registry.curated_dir, skill_registry.curated_fallback_dir]

    post = frontmatter.Post(
        content=content,
        **{
            "name": slug,
            "description": description,
            "tags": FlowList(tags) if isinstance(tags, list) else tags,
            "status": "verified" if category == "curated" else "draft",
            "source": category,
            "version": 1,
        }
    )

    serialized = frontmatter.dumps(post)

    written_paths = []
    for d in target_dirs:
        try:
            if rel_path:
                file_path = d / rel_path
            else:
                file_path = d / f"{slug}.md"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(serialized, encoding="utf-8")
            written_paths.append(str(file_path))
        except Exception as e:
            return f"Error while saving to {d}: {e}"

    skill_registry.reload()

    paths_str = ", ".join(written_paths)
    return f"Skill '{slug}' saved successfully to: {paths_str}. Registry reloaded."


@mcp.tool()
def skill_delete(name: str) -> str:
    """Delete an existing skill from the filesystem and registry."""
    import os
    enabled = os.getenv("AION_SKILL_WRITE_ENABLED", "1").lower() in ("1", "true", "yes", "on")
    if not enabled:
        return "Error: skill write/delete (AION_SKILL_WRITE_ENABLED) is disabled for this MCP server."

    import re
    from pathlib import Path

    slug = re.sub(r"[^a-z0-9-]+", "", name.lower().replace("_", "-").strip())

    # Determine the relative path of the existing skill to delete it correctly from all directories
    existing_path = skill_registry.get_skill_path(slug)
    rel_path = None
    if existing_path:
        existing_path = Path(existing_path)
        for base_dir in (skill_registry.curated_dir, skill_registry.curated_fallback_dir, skill_registry.generated_dir):
            try:
                rel_path = existing_path.relative_to(base_dir)
                break
            except ValueError:
                continue

    deleted_from = []
    for d in [skill_registry.curated_dir, skill_registry.curated_fallback_dir, skill_registry.generated_dir]:
        file_path = d / f"{slug}.md"

        if file_path.exists():
            try:
                file_path.unlink()
                deleted_from.append(str(file_path))
            except Exception as e:
                return f"Error while deleting {file_path}: {e}"

    skill_registry.reload()

    if deleted_from:
        paths_str = ", ".join(deleted_from)
        return f"Skill '{slug}' deleted successfully from: {paths_str}. Registry reloaded."
    else:
        # Fallback alla cancellazione tramite registry se non trovata fisicamente
        if skill_registry.delete_skill(slug):
            return f"Skill '{slug}' deleted via registry."
        return f"Skill '{slug}' not found."


if __name__ == "__main__":

    async def main():
        try:
            from mcp.server.stdio import stdio_server

            async with stdio_server() as (read_stream, write_stream):
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(),
                )
        except Exception:
            os.makedirs("data", exist_ok=True)
            with open("data/mcp_debug.log", "a", encoding="utf-8") as f:
                f.write("\n--- SKILLS_HUB CRASH ---\n")
                f.write(traceback.format_exc())
            raise

    asyncio.run(main())
