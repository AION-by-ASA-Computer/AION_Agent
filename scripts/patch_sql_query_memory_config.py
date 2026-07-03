#!/usr/bin/env python3
"""
Propaga skill e patch profilo Postgres per QueryMemory SQL in config/ (locale).

- Copia config_std/skills/sql_query_memory_protocol.md → config/skills/ (se mancante o --force)
- Aggiorna config/profiles/postgres_metadata_assistant.yaml (skill, native_tool_groups, istruzioni)
- Riscrive config_std/profiles/postgres_metadata_assistant.yaml dal profilo locale patchato (formato |)

Chiamato da setup_core.py e upgrade_core.py dopo sync_config.
Vedi anche patch_mempalace_navigation_config.py (layer navigazione MemPalace).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STD_SKILL = ROOT / "config_std" / "skills" / "sql_query_memory_protocol.md"
LOCAL_SKILL = ROOT / "config" / "skills" / "sql_query_memory_protocol.md"
LOCAL_PROFILE = ROOT / "config" / "profiles" / "postgres_metadata_assistant.yaml"
STD_PROFILE = ROOT / "config_std" / "profiles" / "postgres_metadata_assistant.yaml"
LOCAL_CORE = ROOT / "config" / "skills" / "core_protocol.md"
STD_CORE = ROOT / "config_std" / "skills" / "core_protocol.md"

QM_MARKER = "QUERYMEMORY SQL"
QM_INSTRUCTIONS_BLOCK = """QUERYMEMORY SQL (MANDATORY):
- Before writing new SQL on PostgreSQL, call `sql_memory_search` or `search_known_sql` for the active project (cassetto: default, vendite, tecnico, …). If unsure, call `sql_memory_list_projects` / `list_sql_projects`.
- Reuse or adapt validated SQL from hits (score ≥ 0.8). Do not run broad `information_schema` / `pg_catalog` exploration unless the cache has no match.
- After a verified successful business answer, call `sql_memory_save` / `save_successful_sql` with `is_verified=true` only when results are correct.
- Follow the `sql_query_memory_protocol` skill. Never use PromQL memory tools (`search_known_query`, `save_successful_query`) for SQL.

"""

CORE_QM_LINE = (
    "- **QueryMemory SQL** *(native `sql_query_memory` and/or **memory** MCP)*: "
    "Cache for validated **PostgreSQL SELECT** per project (cassetto). "
    "Use `sql_memory_search` / `search_known_sql` before new SQL; "
    "`sql_memory_save` / `save_successful_sql` after success.\n"
)


def _load_profile_yaml(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        import yaml  # type: ignore
    except ImportError:
        print("ERRORE: PyYAML richiesto per patch profilo", file=sys.stderr)
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _dump_profile_yaml(path: Path, data: dict) -> None:
    """Scrivi profilo con instructions: | (leggibile, senza escape JSON)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"name: {data.get('name', 'Postgres Metadata Assistant')}")
    desc = (data.get("description") or "").strip()
    if "\n" in desc:
        lines.append("description: |")
        for ln in desc.splitlines():
            lines.append(f"  {ln}")
    else:
        lines.append(f"description: {desc}")
    lines.append("instructions: |")
    instr = (data.get("instructions") or "").rstrip()
    for ln in instr.splitlines():
        lines.append(f"  {ln}")
    lines.append("skills:")
    for sk in data.get("skills") or []:
        lines.append(f"  - {sk}")
    lines.append("mcp_servers:")
    for srv in data.get("mcp_servers") or []:
        lines.append(f"  - {srv}")
    ntg = data.get("native_tool_groups")
    lines.append("native_tool_groups:")
    if ntg:
        for g in ntg:
            lines.append(f"  - {g}")
    else:
        lines.append("  []")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _patch_instructions(instr: str) -> tuple[str, bool]:
    if QM_MARKER in instr:
        return instr, False
    marker = "OPERATIONAL GUIDELINES (MANDATORY AND BINDING):\n\n"
    if marker in instr:
        patched = instr.replace(marker, marker + QM_INSTRUCTIONS_BLOCK, 1)
        return patched, True
    return QM_INSTRUCTIONS_BLOCK + instr, True


def _patch_skills(skills: list) -> tuple[list, bool]:
    out = list(skills or [])
    if "sql_query_memory_protocol" in out:
        return out, False
    insert_after = "openmetadata_guide"
    if insert_after in out:
        idx = out.index(insert_after) + 1
        out.insert(idx, "sql_query_memory_protocol")
    else:
        out.append("sql_query_memory_protocol")
    return out, True


def _patch_native_groups(ntg: list | None) -> tuple[list, bool]:
    out = list(ntg or [])
    if "sql_query_memory" in out:
        return out, False
    out.append("sql_query_memory")
    return out, True


def _strip_removed_nav_skill(skills: list) -> tuple[list, bool]:
    out = [s for s in (skills or []) if s != "db_navigation_map"]
    return out, len(out) != len(skills or [])


def _profile_base_dict() -> dict | None:
    """Prefer config_std when local profile still lists db_navigation_map but std does not."""
    std = _load_profile_yaml(STD_PROFILE)
    local = _load_profile_yaml(LOCAL_PROFILE)
    if std and local:
        std_skills = set(std.get("skills") or [])
        local_skills = set(local.get("skills") or [])
        if (
            "db_navigation_map" in local_skills
            and "db_navigation_map" not in std_skills
        ):
            print(
                f"  [INFO] {LOCAL_PROFILE.relative_to(ROOT)} usa config_std come base "
                f"(db_navigation_map rimossa dal profilo standard)"
            )
            return dict(std)
    return local or std


def patch_profile_dict(data: dict) -> bool:
    changed = False
    instr, c1 = _patch_instructions(data.get("instructions") or "")
    if c1:
        data["instructions"] = instr
        changed = True
    skills, c2 = _patch_skills(data.get("skills") or [])
    if c2:
        data["skills"] = skills
        changed = True
    ntg, c3 = _patch_native_groups(data.get("native_tool_groups"))
    if c3:
        data["native_tool_groups"] = ntg
        changed = True
    return changed


def copy_skill(*, force: bool) -> bool:
    if not STD_SKILL.is_file():
        print(f"WARN: skill standard mancante: {STD_SKILL}")
        return False
    LOCAL_SKILL.parent.mkdir(parents=True, exist_ok=True)
    if LOCAL_SKILL.exists() and not force:
        return False
    shutil.copy2(STD_SKILL, LOCAL_SKILL)
    print(f"  [COPY] {LOCAL_SKILL.relative_to(ROOT)}")
    return True


def patch_core_protocol(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if "QueryMemory SQL" in text:
        return False
    anchor = (
        "- **QueryMemory (PromQL Cache)** *(requires **memory** MCP)*: "
        "Cache for validated **PromQL** only. Use `search_known_query` / `save_successful_query` — never for SQL.\n"
    )
    if anchor not in text:
        return False
    path.write_text(text.replace(anchor, anchor + CORE_QM_LINE, 1), encoding="utf-8")
    print(f"  [PATCH] {path.relative_to(ROOT)} (core_protocol QueryMemory SQL)")
    return True


def run(*, force_skill: bool = False, sync_std_profile: bool = True) -> int:
    print("\n--- Patch QueryMemory SQL (config locale) ---\n")
    copy_skill(force=force_skill)
    patch_core_protocol(LOCAL_CORE)
    patch_core_protocol(STD_CORE)

    data = _profile_base_dict()
    if data is None:
        print("  Nessun profilo postgres_metadata_assistant in config/ o config_std/.")
        return 0

    skills, stripped = _strip_removed_nav_skill(data.get("skills") or [])
    if stripped:
        data["skills"] = skills
        print(f"  [PATCH] rimosso db_navigation_map da skills profilo locale")

    if patch_profile_dict(data):
        _dump_profile_yaml(LOCAL_PROFILE, data)
        print(f"  [PATCH] {LOCAL_PROFILE.relative_to(ROOT)}")
    else:
        print(f"  [OK] {LOCAL_PROFILE.relative_to(ROOT)} già aggiornato")

    if sync_std_profile:
        skills_std, _ = _strip_removed_nav_skill(data.get("skills") or [])
        data["skills"] = skills_std
        _dump_profile_yaml(STD_PROFILE, data)
        print(
            f"  [SYNC] {STD_PROFILE.relative_to(ROOT)} ← profilo locale (QM patch, senza db_navigation_map)"
        )

    print("")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Patch config/ per QueryMemory SQL (Postgres profile)"
    )
    ap.add_argument(
        "--force-skill",
        action="store_true",
        help="Sovrascrive config/skills/sql_query_memory_protocol.md",
    )
    ap.add_argument(
        "--no-sync-std-profile",
        action="store_true",
        help="Non riscrive config_std/profiles/postgres_metadata_assistant.yaml",
    )
    args = ap.parse_args()
    return run(
        force_skill=args.force_skill, sync_std_profile=not args.no_sync_std_profile
    )


if __name__ == "__main__":
    raise SystemExit(main())
