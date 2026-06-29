#!/usr/bin/env python3
"""
Propaga skill e profilo Postgres per MemPalace navigazione (wing_proj_{project}).

- Copia skill da config_std/skills/ → config/skills/
- Allinea config/profiles/postgres_metadata_assistant.yaml da config_std se il locale
  non ha ancora MEMORY LAYERS / MEMPALACE NAVIGATION
- Opzionale: bootstrap drawer da db_navigation_map (--bootstrap-mempalace)

Chiamato da setup_core.py e upgrade_core.py dopo sync_config / patch SQL QM.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SKILLS = (
    "datasource_memory_protocol.md",
    "mempalace_protocol.md",
)

_REMOVED_NAV_SKILL = "postgres_navigation_memory_protocol"

STD_PROFILE = ROOT / "config_std" / "profiles" / "postgres_metadata_assistant.yaml"
LOCAL_PROFILE = ROOT / "config" / "profiles" / "postgres_metadata_assistant.yaml"
BOOTSTRAP_SCRIPT = ROOT / "scripts" / "bootstrap_db_navigation_mempalace.py"
STD_MCP_REGISTRY = ROOT / "config_std" / "mcp_registry.yaml"
LOCAL_MCP_REGISTRY = ROOT / "config" / "mcp_registry.yaml"
_SKILL_VIEW_ENV_KEY = "AION_SKILL_VIEW_ENFORCE_PROFILE"

DATASOURCE_MEMORY_SKILL = "datasource_memory_protocol"
REMOVED_NAV_SKILL = "db_navigation_map"
_STD_MYSQL_PROFILE = ROOT / "config_std" / "profiles" / "mysql_metadata_assistant.yaml"
_LOCAL_MYSQL_PROFILE = ROOT / "config" / "profiles" / "mysql_metadata_assistant.yaml"


def _copy_skills(*, force: bool) -> int:
    copied = 0
    dst_dir = ROOT / "config" / "skills"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in _SKILLS:
        src = ROOT / "config_std" / "skills" / name
        dst = dst_dir / name
        if not src.is_file():
            print(f"  [WARN] skill standard mancante: {src.relative_to(ROOT)}")
            continue
        if dst.exists() and not force:
            print(f"  [OK] {dst.relative_to(ROOT)}")
            continue
        shutil.copy2(src, dst)
        print(f"  [COPY] {dst.relative_to(ROOT)}")
        copied += 1
    return copied


def _local_still_has_removed_nav_skill() -> bool:
    if not LOCAL_PROFILE.is_file() or not STD_PROFILE.is_file():
        return False
    local = LOCAL_PROFILE.read_text(encoding="utf-8")
    std = STD_PROFILE.read_text(encoding="utf-8")
    if _REMOVED_NAV_SKILL in local and _REMOVED_NAV_SKILL not in std:
        return True
    return (
        f"  - {REMOVED_NAV_SKILL}\n" in local or f"- {REMOVED_NAV_SKILL}" in local
    ) and REMOVED_NAV_SKILL not in std


def _sync_profile_from_std(*, force: bool = False) -> bool:
    if not STD_PROFILE.is_file():
        print(f"  [WARN] profilo standard assente: {STD_PROFILE.relative_to(ROOT)}")
        return False
    std_text = STD_PROFILE.read_text(encoding="utf-8")
    if DATASOURCE_MEMORY_SKILL not in std_text:
        print(f"  [WARN] config_std profilo senza {DATASOURCE_MEMORY_SKILL}")
        return False

    local_text = ""
    if LOCAL_PROFILE.is_file():
        local_text = LOCAL_PROFILE.read_text(encoding="utf-8")

    needs = force or _local_still_has_removed_nav_skill()
    if (
        not needs
        and DATASOURCE_MEMORY_SKILL in local_text
        and _REMOVED_NAV_SKILL not in local_text
    ):
        print(f"  [OK] {LOCAL_PROFILE.relative_to(ROOT)} già allineato a config_std")
    else:
        LOCAL_PROFILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(STD_PROFILE, LOCAL_PROFILE)
        reason = "force" if force else "skill memoria datasource"
        print(f"  [SYNC] {LOCAL_PROFILE.relative_to(ROOT)} ← config_std ({reason})")

    if _STD_MYSQL_PROFILE.is_file():
        LOCAL_PROFILE.parent.mkdir(parents=True, exist_ok=True)
        if force or not _LOCAL_MYSQL_PROFILE.is_file() or _REMOVED_NAV_SKILL in (
            _LOCAL_MYSQL_PROFILE.read_text(encoding="utf-8")
            if _LOCAL_MYSQL_PROFILE.is_file()
            else ""
        ):
            shutil.copy2(_STD_MYSQL_PROFILE, _LOCAL_MYSQL_PROFILE)
            print(f"  [SYNC] {_LOCAL_MYSQL_PROFILE.relative_to(ROOT)} ← config_std")

    return needs or DATASOURCE_MEMORY_SKILL not in local_text


def _patch_mcp_registry_skill_view_enforce() -> bool:
    """Ensure config/mcp_registry.yaml skills_hub env has AION_SKILL_VIEW_ENFORCE_PROFILE."""
    if not STD_MCP_REGISTRY.is_file() or not LOCAL_MCP_REGISTRY.is_file():
        return False
    try:
        import yaml  # type: ignore
    except ImportError:
        print("  [WARN] PyYAML assente — skip patch mcp_registry skills_hub env")
        return False
    std = yaml.safe_load(STD_MCP_REGISTRY.read_text(encoding="utf-8")) or {}
    local = yaml.safe_load(LOCAL_MCP_REGISTRY.read_text(encoding="utf-8")) or {}
    std_hub = (std.get("skills_hub") or {}).get("env") or {}
    want = std_hub.get(_SKILL_VIEW_ENV_KEY, "1")
    hub = local.setdefault("skills_hub", {})
    env = hub.setdefault("env", {})
    if env.get(_SKILL_VIEW_ENV_KEY) == want:
        print(f"  [OK] {LOCAL_MCP_REGISTRY.relative_to(ROOT)} skills_hub.{_SKILL_VIEW_ENV_KEY}")
        return False
    env[_SKILL_VIEW_ENV_KEY] = want
    LOCAL_MCP_REGISTRY.write_text(
        yaml.safe_dump(local, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"  [PATCH] {LOCAL_MCP_REGISTRY.relative_to(ROOT)} → skills_hub.env.{_SKILL_VIEW_ENV_KEY}={want}")
    return True


def _run_bootstrap(project: str, dry_run: bool) -> int:
    if not BOOTSTRAP_SCRIPT.is_file():
        print(f"  [WARN] bootstrap script assente: {BOOTSTRAP_SCRIPT.name}")
        return 0
    import subprocess

    cmd = [sys.executable, str(BOOTSTRAP_SCRIPT), "--project", project]
    if dry_run:
        cmd.append("--dry-run")
    print(f"  [BOOTSTRAP] {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def run(
    *,
    force_skills: bool = False,
    sync_profile: bool = True,
    force_profile_sync: bool = False,
    bootstrap: bool = False,
    bootstrap_project: str = "default",
    bootstrap_dry_run: bool = False,
) -> int:
    print("\n--- Patch MemPalace navigazione (config locale) ---\n")
    _copy_skills(force=force_skills)
    _patch_mcp_registry_skill_view_enforce()
    if sync_profile:
        _sync_profile_from_std(force=force_profile_sync)
    if bootstrap:
        rc = _run_bootstrap(bootstrap_project, bootstrap_dry_run)
        if rc != 0:
            print("  [WARN] bootstrap MemPalace exited non-zero (MCP mempalace disponibile?)")
            return rc
    print("")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch config/ per MemPalace navigazione ERP")
    ap.add_argument("--force-skills", action="store_true", help="Sovrascrive skill mempalace in config/skills/")
    ap.add_argument(
        "--no-sync-profile",
        action="store_true",
        help="Non allinea config/profiles/postgres_metadata_assistant.yaml da config_std",
    )
    ap.add_argument(
        "--force-profile-sync",
        action="store_true",
        help="Sovrascrive config/profiles/postgres_metadata_assistant.yaml da config_std",
    )
    ap.add_argument(
        "--bootstrap-mempalace",
        action="store_true",
        help="Esegue bootstrap_db_navigation_mempalace.py (richiede MCP mempalace)",
    )
    ap.add_argument("--bootstrap-project", default="default", help="Slug progetto per bootstrap")
    ap.add_argument(
        "--bootstrap-dry-run",
        action="store_true",
        help="Solo anteprima chunk bootstrap",
    )
    args = ap.parse_args()
    return run(
        force_skills=args.force_skills,
        sync_profile=not args.no_sync_profile,
        force_profile_sync=args.force_profile_sync,
        bootstrap=args.bootstrap_mempalace,
        bootstrap_project=args.bootstrap_project.strip(),
        bootstrap_dry_run=args.bootstrap_dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
