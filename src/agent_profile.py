import logging
import os
import re
import shutil
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Iterator

logger = logging.getLogger("aion.agent_profile")

_PROFILE_STEM_RE = re.compile(r"^[a-z0-9_]+$")

from .runtime.profile_schema import (
    ProfileSchema,
    ProfileValidationIssue,
    ProfileValidationReport,
    log_validation_report,
    validate_profile_references,
)
from .runtime.skill_alias import resolve_skill_alias  # noqa: F401 — P2.4
from .skill_registry import skill_registry


class ProfileNotFoundError(ValueError):
    """Raised when profile slug cannot be resolved (no silent fallback)."""

    def __init__(self, profile_name: str, available_slugs: List[str]):
        self.profile_name = profile_name
        self.available_slugs = list(available_slugs)
        msg = (
            f"Profile '{profile_name}' not found. "
            f"Available slugs: {', '.join(available_slugs) or '(none)'}"
        )
        super().__init__(msg)


def _legacy_name_lookup_enabled() -> bool:
    return os.getenv("AION_PROFILE_LEGACY_NAME_LOOKUP", "0").lower() in (
        "1",
        "true",
        "yes",
    )


def _profile_hot_reload_enabled() -> bool:
    return os.getenv("AION_PROFILE_HOT_RELOAD", "0").lower() in ("1", "true", "yes")


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def _resolve_profiles_path(raw: str) -> Path:
    base = Path(raw)
    return base if base.is_absolute() else _repo_root() / base


def profiles_std_path() -> Path:
    """Synced standard profiles (``config/profiles`` by default)."""
    return _resolve_profiles_path(os.getenv("AION_PROFILES_STD_DIR", "config/profiles"))


def profiles_write_path() -> Path:
    """Writable overlay; defaults to std path when ``AION_PROFILES_WRITE_DIR`` is unset."""
    override = (os.getenv("AION_PROFILES_WRITE_DIR") or "").strip()
    if override:
        return _resolve_profiles_path(override)
    return profiles_std_path()


def profiles_template_path() -> Path:
    """Git-tracked templates used to detect local customizations."""
    return _resolve_profiles_path(
        os.getenv("AION_PROFILES_TEMPLATE_DIR", "config_std/profiles")
    )


def _iter_profile_yaml_files(directory: Path) -> Iterator[Path]:
    if not directory.is_dir():
        return
    for file in sorted(directory.glob("*.yaml")):
        stem_low = file.stem.lower()
        if stem_low.endswith("_old") or " copy" in stem_low:
            logger.warning("Skipping non-canonical profile file: %s", file.name)
            continue
        if not _PROFILE_STEM_RE.match(stem_low):
            logger.warning(
                "Skipping profile with invalid slug characters: %s (use [a-z0-9_])",
                file.name,
            )
            continue
        yield file


def _yaml_files_differ(a: Path, b: Path) -> bool:
    if not a.is_file() or not b.is_file():
        return True
    try:
        return a.read_bytes() != b.read_bytes()
    except OSError:
        return True


def migrate_profiles_to_write_dir(*, dry_run: bool = False) -> int:
    """Copy customized ``config/profiles`` YAML into the writable overlay (one-time safe).

    Copies when the runtime file differs from ``config_std/profiles`` and the overlay
    does not already contain that slug. Returns the number of files copied.
    """
    std_dir = profiles_std_path()
    write_dir = profiles_write_path()
    template_dir = profiles_template_path()
    if write_dir.resolve() == std_dir.resolve():
        return 0
    copied = 0
    if not dry_run:
        write_dir.mkdir(parents=True, exist_ok=True)
    for src in _iter_profile_yaml_files(std_dir):
        dest = write_dir / src.name
        if dest.is_file():
            continue
        template = template_dir / src.name
        if template.is_file() and not _yaml_files_differ(src, template):
            continue
        if dry_run:
            copied += 1
            continue
        shutil.copy2(src, dest)
        logger.info("Migrated profile overlay: %s -> %s", src, dest)
        copied += 1
    return copied


# Full inlined bodies when AION_SKILL_SYSTEM_PROMPT_MODE=index unless overridden per profile.
DEFAULT_CRITICAL_SKILL_NAMES = frozenset(
    {"core_protocol", "artifact_protocol", "agent_db_protocol"}
)

# Always inlined for every profile (global golden rules, thinking contract, anti-loop).
ALWAYS_CRITICAL_SKILL_NAMES = frozenset({"core_protocol"})

_WARNED_FULL_SKILL_MODE = False


class AgentProfile:
    def __init__(
        self,
        name: str,
        description: str,
        instructions: str,
        skills: List[str],
        mcp_servers: List[str] = None,
        slug: Optional[str] = None,
        critical_skills: Optional[List[str]] = None,
        native_tool_groups: Optional[List[str]] = None,
        wren_project_path: Optional[str] = None,
        max_agent_steps: Optional[int] = None,
    ):
        self.name = name
        self.description = description
        self.instructions = instructions
        self.skills = skills
        self.mcp_servers = mcp_servers or []
        self.native_tool_groups = list(native_tool_groups or [])
        self.slug = slug or name.replace(" ", "_").lower()
        self.critical_skills = critical_skills
        self.wren_project_path = (wren_project_path or "").strip() or None
        self.max_agent_steps = max_agent_steps

    def _resolved_critical_skill_names(self) -> frozenset:
        if self.critical_skills is None:
            base = DEFAULT_CRITICAL_SKILL_NAMES
        else:
            base = frozenset(self.critical_skills)
        return ALWAYS_CRITICAL_SKILL_NAMES | base

    def generate_system_prompt(
        self,
        user_id: str = "default",
        *,
        provider: str = "",
        model_id: str = "",
    ) -> str:
        """System prompt: istruzioni + skill (index o full legacy) + opz. MEMORY/USER."""
        from datetime import datetime

        skill_registry.reload_if_stale()

        mode = os.getenv("AION_SKILL_SYSTEM_PROMPT_MODE", "index").lower()
        global _WARNED_FULL_SKILL_MODE
        if mode == "full" and not _WARNED_FULL_SKILL_MODE:
            import logging

            _WARNED_FULL_SKILL_MODE = True
            logging.getLogger("aion.agent_profile").warning(
                "AION_SKILL_SYSTEM_PROMPT_MODE=full inlines every profile skill in the system "
                "prompt; use 'index' + critical_skills for smaller prompts."
            )

        # Sostituzione placeholder dinamici nelle istruzioni
        instructions = self.instructions
        now = datetime.now()
        instructions = instructions.replace(
            "{{current_date}}", now.strftime("%Y-%m-%d")
        )
        instructions = instructions.replace(
            "{{current_time}}", now.strftime("%H:%M:%S")
        )

        parts = [f"# Role: {self.name}", instructions]

        try:
            from .runtime.system_prompt import assemble_model_prompt_section

            model_extra = assemble_model_prompt_section(
                provider=provider, model_id=model_id
            )
            if model_extra:
                parts.append(model_extra)
        except Exception:
            pass

        try:
            from .mcp_manager import mcp_manager
            from .runtime.mcp_tooling_prompt import build_mcp_tooling_prompt_section

            mcp_extra = build_mcp_tooling_prompt_section(
                self.mcp_servers, mcp_manager.get_server_config
            )
            if mcp_extra:
                parts.append(mcp_extra)
        except Exception:
            pass

        if mode == "full":
            parts.append("\n## Skills and rules")
            for skill_name in self.skills:
                actual_name = resolve_skill_alias(skill_name)

                body = skill_registry.get_skill_full(actual_name)
                if body:
                    parts.append(body)
        else:
            critical_skills = self._resolved_critical_skill_names()

            # 1. Critical full content (core_protocol always; see ALWAYS_CRITICAL_SKILL_NAMES)
            inlined_critical: set[str] = set()
            for skill_name in self.skills:
                if skill_name in critical_skills:
                    actual_name = resolve_skill_alias(skill_name)

                    body = skill_registry.get_skill_full(actual_name)
                    if body:
                        # Display it as 'artifact_protocol' to the agent for consistency
                        display_name = (
                            "artifact_protocol"
                            if skill_name == "artifact_protocol"
                            else skill_name
                        )
                        parts.append(f"\n### Protocol rules ({display_name})\n{body}")
                        inlined_critical.add(skill_name)

            for skill_name in sorted(critical_skills - inlined_critical):
                if skill_name not in self.skills:
                    body = skill_registry.get_skill_full(skill_name)
                    if body:
                        parts.append(f"\n### Protocol rules ({skill_name})\n{body}")
                        inlined_critical.add(skill_name)

            # 2. Others as summaries
            other_skills = [s for s in self.skills if s not in critical_skills]
            summaries = skill_registry.list_summaries(allowed_names=other_skills)
            if summaries:
                parts.append("\n## Other available skills")
                parts.append(
                    "Skills below are index-only. **Required** before code, office documents "
                    "(.docx/.pdf/.xlsx/.pptx), or specialized tasks: "
                    "1) `skill_search` on skills_hub with a relevant query; "
                    "2) `skill_view` with the exact skill slug. "
                    "Do not improvise workflows when a listed skill applies."
                )
                for s in summaries:
                    tags = ", ".join(s.get("tags") or []) or "—"
                    parts.append(
                        f"- **`{s['name']}`** ({tags}): {s.get('description', '')}"
                    )
                try:
                    from .runtime.system_prompt import build_skills_catalog_xml

                    catalog = build_skills_catalog_xml(allowed_names=other_skills)
                    if catalog:
                        parts.append(catalog)
                except Exception:
                    pass

        if os.getenv("AION_SOUL_MEMORY_USER_SPLIT", "0").lower() in (
            "1",
            "true",
            "yes",
        ):
            from .memory.memory_files import ProfileMemoryBundle

            snap = ProfileMemoryBundle(self.slug, user_id).snapshot()
            if snap.get("soul"):
                parts.insert(0, snap["soul"])
            if snap.get("memory"):
                parts.append(f"## OPERATIONAL MEMORY (agent)\n{snap['memory']}")
            if snap.get("user"):
                parts.append(f"## USER PREFERENCES\n{snap['user']}")

        # 3. Final enforcement instructions (at the bottom to avoid being forgotten)
        # if "doc_extractor" in self.slug:
        #     parts.append(
        #         "\n## REGOLA MANDATORIA DI OUTPUT\n"
        #         "1. Puoi includere brevi messaggi di testo per informare l'utente sull'avanzamento (es. 'Sto leggendo il file...', 'Cerco il contratto nel database...').\n"
        #         "2. Il risultato finale DEVE essere un blocco di codice JSON racchiuso in ```json ... ```.\n"
        #         "3. Non aggiungere commenti discorsivi DOPO il blocco JSON."
        #     )

        return "\n\n".join(parts)


class ProfileManager:
    """Load profiles from std dir + optional writable overlay (overlay wins per slug)."""

    def __init__(self, profiles_dir: str | None = None):
        if profiles_dir is not None:
            self.std_path = (
                Path(profiles_dir)
                if Path(profiles_dir).is_absolute()
                else _repo_root() / profiles_dir
            )
            self.write_path = self.std_path
        else:
            self.std_path = profiles_std_path()
            self.write_path = profiles_write_path()
        # Admin API writes here (backward-compatible alias).
        self.base_path = self.write_path
        self._profiles: Dict[str, AgentProfile] = {}
        self._by_slug: Dict[str, AgentProfile] = {}
        self._dir_mtime: float = 0.0
        migrate_profiles_to_write_dir()
        self.load_all()

    def _profile_dirs(self) -> List[Path]:
        if self.write_path.resolve() == self.std_path.resolve():
            return [self.std_path]
        return [self.std_path, self.write_path]

    def profile_yaml_path(self, slug: str, *, for_write: bool = False) -> Path:
        if for_write:
            return self.write_path / f"{slug}.yaml"
        overlay = self.write_path / f"{slug}.yaml"
        if overlay.is_file():
            return overlay
        return self.std_path / f"{slug}.yaml"

    def _compute_dir_mtime(self) -> float:
        mtimes: List[float] = []
        for directory in self._profile_dirs():
            if not directory.exists():
                continue
            try:
                mtimes.append(directory.stat().st_mtime)
            except OSError:
                continue
            for file in directory.glob("*.yaml"):
                try:
                    mtimes.append(file.stat().st_mtime)
                except OSError:
                    continue
        return max(mtimes) if mtimes else 0.0

    def invalidate(self) -> None:
        self._dir_mtime = 0.0

    def load_all_if_stale(self, *, force: bool = False) -> None:
        if force:
            self.load_all()
            return
        current = self._compute_dir_mtime()
        if current != self._dir_mtime:
            self.load_all()

    def _load_profile_file(self, file: Path) -> Optional[AgentProfile]:
        stem_low = file.stem.lower()
        with open(file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        try:
            schema = ProfileSchema.from_yaml_dict(data, stem_low)
        except Exception as exc:
            logger.error("Invalid profile %s: %s", file.name, exc)
            return None
        return AgentProfile(
            name=schema.name,
            description=schema.description,
            instructions=schema.instructions,
            skills=schema.skills,
            mcp_servers=schema.mcp_servers,
            slug=stem_low,
            critical_skills=schema.critical_skills,
            native_tool_groups=schema.native_tool_groups,
            wren_project_path=schema.wren_project_path,
            max_agent_steps=schema.max_agent_steps,
        )

    def load_all(self):
        self._profiles.clear()
        self._by_slug.clear()
        for directory in self._profile_dirs():
            for file in _iter_profile_yaml_files(directory):
                profile = self._load_profile_file(file)
                if not profile:
                    continue
                self._profiles[profile.name] = profile
                self._by_slug[profile.slug] = profile
        self._dir_mtime = self._compute_dir_mtime()

    def validate_all(self) -> ProfileValidationReport:
        from .mcp_manager import mcp_manager

        report = ProfileValidationReport()
        files_by_slug: Dict[str, Path] = {}
        for directory in self._profile_dirs():
            for file in _iter_profile_yaml_files(directory):
                files_by_slug[file.stem.lower()] = file
        for stem_low, file in files_by_slug.items():
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                schema = ProfileSchema.from_yaml_dict(data, stem_low)
            except Exception as exc:
                report.issues.append(
                    ProfileValidationIssue(stem_low, "error", str(exc))
                )
                continue
            ref_report = validate_profile_references(
                schema,
                stem_low,
                skill_exists=skill_registry.skill_exists,
                server_exists=mcp_manager.server_exists,
            )
            report.merge(ref_report)
        return report

    def get_profile(self, name: str) -> Optional[AgentProfile]:
        if not name:
            return None
        key = name.strip().lower()
        if key in self._by_slug:
            return self._by_slug[key]
        if _legacy_name_lookup_enabled():
            if name in self._profiles:
                return self._profiles[name]
            norm = name.replace(" ", "_").lower()
            if norm in self._by_slug:
                return self._by_slug[norm]
            for p in self._profiles.values():
                if p.name.replace(" ", "_").lower() == norm:
                    return p
        return None

    def resolve_profile(self, profile_name: str) -> AgentProfile:
        """Canonical slug resolution with optional AION_DEFAULT_PROFILE fallback."""
        self.load_all_if_stale(force=_profile_hot_reload_enabled())
        profile = self.get_profile(profile_name)
        if not profile:
            default_slug = (os.getenv("AION_DEFAULT_PROFILE") or "aion_std").strip()
            if default_slug and default_slug != profile_name:
                profile = self.get_profile(default_slug)
        if not profile:
            raise ProfileNotFoundError(
                profile_name,
                sorted(self._by_slug.keys()),
            )
        return profile

    def delete_profile(self, name: str) -> bool:
        p = self.get_profile(name)
        if not p:
            return False
        removed = False
        write_file = self.write_path / f"{p.slug}.yaml"
        std_file = self.std_path / f"{p.slug}.yaml"
        if write_file.is_file():
            write_file.unlink()
            removed = True
        if std_file.is_file() and std_file.resolve() != write_file.resolve():
            try:
                std_file.unlink()
                removed = True
            except OSError as exc:
                logger.warning("Could not delete std profile %s: %s", std_file, exc)
        self.load_all()
        return removed

    def list_profiles(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": p.name,
                "description": p.description,
                "slug": p.slug,
                "skills": p.skills,
                "mcp_servers": p.mcp_servers,
                "native_tool_groups": list(
                    getattr(p, "native_tool_groups", None) or []
                ),
            }
            for p in self._profiles.values()
        ]


profile_manager = ProfileManager()
