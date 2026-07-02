# src/api/admin.py
import logging
import os
import yaml
import frontmatter
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File
import io
import zipfile
import shutil
import copy
from pydantic import BaseModel, Field
from ..agent_profile import profile_manager, AgentProfile
from ..skill_registry import skill_registry
from ..mcp_manager import mcp_manager
from ..security.checker import AIONAntivirus
from ..marketplaces.market_adapters import hub_aggregator, npx_invoke_args
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from sse_starlette.sse import EventSourceResponse


class FlowList(list):
    pass


def flow_list_representer(dumper, data):
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


yaml.add_representer(FlowList, flow_list_representer, Dumper=yaml.SafeDumper)
try:
    from yaml import CSafeDumper

    yaml.add_representer(FlowList, flow_list_representer, Dumper=CSafeDumper)
except ImportError:
    pass
from ..agent_pipeline import AgentPipeline
from ..main import get_agent, set_event_loop
from mcp import StdioServerParameters
from .auth_login import require_admin_role
from .settings_api import router as settings_router

from .ltm_admin import router as ltm_admin_router
from .admin_profile_memory import router as admin_profile_memory_router
from .cron_admin import router as cron_admin_router
from .admin_query_memory import router as admin_query_memory_router
from .llm_providers import router as llm_providers_router
from ..runtime.redis_client import redis_status
from ..data.engine import get_async_session_maker
from ..mcp_connector_catalog import (
    infer_connector_id_for_registry_name,
    load_mcp_connector_catalog,
)
from ..data.user_password import UserAlreadyExistsError, create_password_user
from ..data.message_roles import (
    is_empty_technical_message,
    is_ui_visible_role,
    looks_like_internal_content,
    looks_like_raw_plan_content,
    normalize_message_role,
)
from ..data.models import (
    ApiKey,
    Conversation,
    Message,
    Step,
    Attachment,
    SecurityScan,
    TrustedPath,
    McpServerConfig,
)
from ..data.ids import new_uuid7_str
from sqlalchemy import select, delete, func, desc

logger = logging.getLogger("aion.api.admin")


def _synthetic_npx_market_item(item_id: str) -> Optional[Dict[str, Any]]:
    """Build install payload from ``npx:package`` without re-searching marketplaces."""
    s = (item_id or "").strip()
    if not s.lower().startswith("npx:"):
        return None
    pkg = s.split(":", 1)[-1].strip()
    if not pkg:
        return None
    name = pkg.split("/")[-1].replace("@", "").replace(".", "_") or "mcp_npx"
    return {
        "id": s,
        "name": pkg,
        "source": "NPX",
        "description": f"Install via npx: {pkg}",
        "install_type": "npx",
        "npx_package": pkg,
    }


def _synthetic_github_market_item(item_id: str) -> Optional[Dict[str, Any]]:
    """Build install payload from ``github:owner/repo`` (or ``glama:``) without marketplace search."""
    from ..marketplaces.market_adapters import build_github_market_item

    s = (item_id or "").strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith("github:"):
        return build_github_market_item(s)
    if low.startswith("glama:"):
        tail = s.split(":", 1)[-1].strip()
        if tail and "/" in tail:
            return build_github_market_item(f"github:{tail}")
    return None


def _find_marketplace_item(item_id: str) -> Optional[Dict[str, Any]]:
    """Resolve marketplace row by id; tries targeted queries before global search."""
    from ..marketplaces.market_adapters import build_github_market_item, hub_aggregator

    s = (item_id or "").strip()
    synthetic = _synthetic_npx_market_item(s)
    if synthetic:
        return synthetic
    synthetic = _synthetic_github_market_item(s)
    if synthetic:
        return synthetic

    queries: List[str] = []
    if s:
        queries.append(s)
    if ":" in s:
        tail = s.split(":", 1)[-1].strip()
        if tail and tail not in queries:
            queries.append(tail)
    queries.append("")

    def _canonical_github_id(raw: str) -> Optional[str]:
        item = build_github_market_item(raw)
        return str(item.get("id")) if item else None

    def _matches_item(item: Dict[str, Any], wanted: str) -> bool:
        if item.get("id") == wanted:
            return True
        low = wanted.lower()
        if low.startswith("github:") or low.startswith("glama:"):
            wanted_canon = _canonical_github_id(wanted)
            item_canon = _canonical_github_id(str(item.get("id") or ""))
            if wanted_canon and item_canon and wanted_canon == item_canon:
                return True
        if low.startswith("npx:") and item.get("install_type") == "npx":
            wanted_pkg = wanted.split(":", 1)[-1].strip().lower()
            item_pkg = (
                (item.get("npx_package") or item.get("id", "").split(":", 1)[-1])
                .strip()
                .lower()
            )
            if wanted_pkg and item_pkg == wanted_pkg:
                return True
        return False

    for q in queries:
        try:
            items = hub_aggregator.search_all(q)
        except Exception as ex:
            logger.warning("marketplace search_all(%r) failed: %s", q, ex)
            continue
        for item in items:
            if _matches_item(item, item_id):
                return dict(item)
    return None


# --- MODELS ---


class ProfileUpdate(BaseModel):
    name: str
    description: str
    instructions: str
    skills: List[str]
    critical_skills: Optional[List[str]] = None
    mcp_servers: List[str]
    native_tool_groups: Optional[List[str]] = None


class SkillUpdate(BaseModel):
    name: str
    content: str
    metadata: Optional[Dict[str, Any]] = None


class RegistryUpdate(BaseModel):
    servers: Dict[str, Any]


class MCPUpdate(BaseModel):
    model_config = {"extra": "ignore"}

    command: Optional[str] = "python"
    args: Optional[List[str]] = []
    env: Optional[Dict[str, str]] = {}
    description: Optional[str] = ""
    security: Optional[Dict[str, Any]] = {}
    aion_connector_id: Optional[str] = None
    type: Optional[str] = None
    url: Optional[str] = None


class MCPInstallRequest(BaseModel):
    name: str
    script_path: str
    dependencies: Optional[List[str]] = []
    is_sandboxed: Optional[bool] = False


class ScanRequest(BaseModel):
    path: str
    persist: Optional[bool] = True


class TrustRequest(BaseModel):
    path: str


class StmConsolidateBody(BaseModel):
    session_id: str
    profile_name: str = "default"
    user_id: str = "default"
    prune_after: bool = False


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    # Tutte le route ereditano la guard: 401 senza token, 403 senza ruolo "admin".
    # Disabilitabile via AION_ADMIN_PASSWORD_AUTH=0 (escape hatch dev).
    dependencies=[Depends(require_admin_role)],
)


def _message_render_reason_codes(role: str | None, content: str | None) -> List[str]:
    nr = normalize_message_role(role)
    codes: List[str] = []
    if not is_ui_visible_role(nr):
        codes.append("hidden.internal_role")
    if looks_like_internal_content(content):
        codes.append("hidden.internal_marker")
    if looks_like_raw_plan_content(content):
        codes.append("hidden.raw_plan")
    if is_empty_technical_message(nr, content):
        codes.append("hidden.empty_technical")
    if not codes:
        codes.append("shown.ui_visible")
    return codes


router.include_router(settings_router)
router.include_router(ltm_admin_router)
router.include_router(admin_profile_memory_router)
router.include_router(cron_admin_router)
router.include_router(admin_query_memory_router)
router.include_router(llm_providers_router)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_under_dir(path: Path, ancestor: Path) -> bool:
    try:
        path.resolve().relative_to(ancestor.resolve())
        return True
    except ValueError:
        return False


def _remove_market_mcp_artifacts(server_key: str, cfg: Dict[str, Any]) -> None:
    """
    Rimuove clone git / binari scaricati dal marketplace quando l'admin elimina il server.
    Sicurezza: solo sotto ``mcp_servers/`` o ``bin/`` relativi al repo.
    """
    if not cfg:
        return
    root = _project_root().resolve()
    ms_root = (root / "mcp_servers").resolve()
    bin_root = (root / "bin").resolve()

    kind = cfg.get("aion_market_install")
    has_clone_meta = kind == "git" or bool(cfg.get("aion_market_clone_path"))

    if has_clone_meta or (cfg.get("source_id") and (ms_root / server_key).is_dir()):
        rel = cfg.get("aion_market_clone_path")
        if isinstance(rel, str) and rel.strip() and has_clone_meta:
            target = (root / rel.strip()).resolve()
        else:
            target = (ms_root / server_key).resolve()
        if _is_under_dir(target, ms_root) and target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            logger.info("Rimossa directory clone MCP marketplace: %s", target)
        return

    if kind == "binary":
        rel = cfg.get("aion_market_binary_path")
        if isinstance(rel, str) and rel.strip():
            target = (root / rel.strip()).resolve()
        else:
            target = (bin_root / server_key).resolve()
        if _is_under_dir(target, bin_root) and target.is_file():
            try:
                target.unlink()
                logger.info("Rimosso binario MCP marketplace: %s", target)
            except OSError as ex:
                logger.warning("Impossibile rimuovere binario %s: %s", target, ex)


def security_reports_dir() -> Path:
    """
    Report audit sicurezza: default `admin-ui/public/reports` (pannello Next.js).
    Override assoluto: env `AION_SECURITY_REPORTS_DIR`.
    """
    override = (os.environ.get("AION_SECURITY_REPORTS_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _project_root() / "admin-ui" / "public" / "reports"


def _legacy_security_reports_dir() -> Path:
    """Vecchia ubicazione (static/admin); usata solo per leggere report già salvati."""
    return _project_root() / "static" / "admin" / "reports"


@router.get("/security/investigate")
async def investigate_code(path: str, profile: str = "Security Officer"):
    """
    Triggers an LLM-based investigation of a specific file using a selectable profile.
    Returns a stream of tokens and reasoning.
    """

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")

    try:
        with open(path, "r", encoding="utf-8") as f:
            code_content = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read file: {str(e)}")

    set_event_loop(asyncio.get_running_loop())

    # Generate a UNIQUE session ID for each investigation to ensure a fresh context (no history)
    audit_id = f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"

    # Initialize the selected agent profile with the unique session ID
    agent_instance, profile_name = await get_agent(
        profile, session_id=audit_id, user_id="audit"
    )

    pipeline = AgentPipeline(
        agent=agent_instance,
        session_id=audit_id,
        profile_name=profile_name,
        user_id="audit",
    )

    prompt = f"EFFETTUA UN'INDAGINE DI SICUREZZA SUL SEGUENTE FILE:\nPercorso: {path}\n\nCONTENUTO DEL CODICE:\n```python\n{code_content}\n```\n\nIdentifica potenziali minacce e fornisci un verdetto finale."

    REPORTS_DIR = security_reports_dir()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    async def event_generator():
        full_report_content = ""
        # Use the same audit_id generated at the top for the report filename and metadata
        report_id = audit_id
        filename = f"{report_id}.json"

        try:
            async for chunk in pipeline.run_stream(prompt):
                # The pipeline yields 'token' type for text content
                if chunk.get("type") == "token":
                    full_report_content += chunk.get("content", "")

                yield {"event": "message", "data": json.dumps(chunk)}

            # Save the report after generation
            report_data = {
                "id": report_id,
                "timestamp": datetime.now().isoformat(),
                "path": path,
                "profile": profile,
                "content": full_report_content,
            }
            with open(REPORTS_DIR / filename, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2)

            # Also save a markdown version for easier reading
            with open(REPORTS_DIR / f"{report_id}.md", "w", encoding="utf-8") as f:
                f.write(f"# Security Audit Report: {path}\n")
                f.write(f"- Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"- Profile: {profile}\n\n")
                f.write("--- \n\n")
                f.write(full_report_content)

        except Exception as e:
            logger.error(f"Audit generation failed: {e}")
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(
        event_generator(),
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/security/reports")
async def list_security_reports():
    """Lists all saved security audit reports."""
    seen: set[str] = set()
    reports: List[Dict[str, Any]] = []
    for base in (security_reports_dir(), _legacy_security_reports_dir()):
        if not base.exists():
            continue
        for f in base.glob("*.json"):
            try:
                with open(f, "r") as r:
                    data = json.load(r)
                rid = data.get("id")
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                reports.append(
                    {
                        "id": rid,
                        "timestamp": data["timestamp"],
                        "path": data["path"],
                        "profile": data["profile"],
                        "filename": f.name,
                    }
                )
            except Exception:
                continue

    reports.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"reports": reports}


@router.get("/security/report/{report_id}")
async def get_security_report(report_id: str):
    """Retrieves a specific security audit report."""
    primary = security_reports_dir() / f"{report_id}.json"
    legacy = _legacy_security_reports_dir() / f"{report_id}.json"
    report_path = primary if primary.exists() else legacy
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    with open(report_path, "r") as f:
        return json.load(f)


@router.get("/security/scans")
async def list_security_scans(limit: int = 50):
    """Lists recent static analysis scans from the database."""
    async with get_async_session_maker()() as session:
        q = select(SecurityScan).order_by(SecurityScan.timestamp.desc()).limit(limit)
        rows = (await session.execute(q)).scalars().all()
        return {
            "scans": [
                {
                    "id": r.id,
                    "timestamp": r.timestamp,
                    "target_path": r.target_path,
                    "is_safe": r.is_safe,
                }
                for r in rows
            ]
        }


@router.get("/security/scans/{scan_id}")
async def get_security_scan(scan_id: str):
    """Retrieves a specific static analysis scan result."""
    async with get_async_session_maker()() as session:
        r = await session.get(SecurityScan, scan_id)
        if not r:
            raise HTTPException(status_code=404, detail="Scan not found")

        return {
            "id": r.id,
            "timestamp": r.timestamp,
            "target_path": r.target_path,
            "is_safe": r.is_safe,
            "violations": json.loads(r.results_json),
        }


@router.post("/security/scans/{scan_id}/trust")
async def trust_security_scan(scan_id: str, req: TrustRequest):
    """Marks a specific file as trusted WITHIN a specific scan record."""
    async with get_async_session_maker()() as session:
        r = await session.get(SecurityScan, scan_id)
        if not r:
            raise HTTPException(status_code=404, detail="Scan not found")

        violations = json.loads(r.results_json)
        if req.path in violations:
            violations[req.path]["is_trusted"] = True

            # Recalculate is_safe for the record
            r.is_safe = all(
                v.get("is_trusted", False)
                or not any(
                    violation["severity"] in ["high", "critical"]
                    for violation in v.get("list", [])
                )
                for v in violations.values()
            )
            r.results_json = json.dumps(violations)
            await session.commit()

        return {"ok": True, "is_safe": r.is_safe}


# --- ROUTES ---


# --- PROFILES ---


@router.get("/profiles")
async def list_profiles():
    return profile_manager.list_profiles()


@router.get("/profiles/{name}")
async def get_profile(name: str):
    p = profile_manager.get_profile(name)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {
        "name": p.name,
        "slug": p.slug,
        "description": p.description,
        "instructions": p.instructions,
        "skills": list(p.skills or []),
        "mcp_servers": list(p.mcp_servers or []),
        "native_tool_groups": list(getattr(p, "native_tool_groups", None) or []),
        "critical_skills": p.critical_skills,
    }


@router.post("/profiles")
async def save_profile(p: ProfileUpdate):
    from ..runtime.profile_schema import ProfileSchema, validate_profile_references
    from ..skill_registry import skill_registry
    from ..mcp_manager import mcp_manager

    slug = (getattr(p, "slug", None) or p.name).strip().lower().replace(" ", "_")
    file_path = profile_manager.profile_yaml_path(slug, for_write=True)
    existing: Dict[str, Any] = {}
    existing_path = profile_manager.profile_yaml_path(slug)
    if existing_path.is_file():
        with open(existing_path, encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}
    data: Dict[str, Any] = {
        "name": p.name,
        "description": p.description,
        "instructions": p.instructions,
        "skills": p.skills,
        "mcp_servers": p.mcp_servers,
    }
    if p.critical_skills:
        data["critical_skills"] = p.critical_skills
    data["mcp_servers"] = p.mcp_servers
    if p.native_tool_groups is not None:
        data["native_tool_groups"] = p.native_tool_groups
    elif "native_tool_groups" in existing:
        data["native_tool_groups"] = existing["native_tool_groups"]
    if p.critical_skills is not None:
        data["critical_skills"] = p.critical_skills
    elif "critical_skills" in existing:
        data["critical_skills"] = existing["critical_skills"]
    try:
        schema = ProfileSchema.from_yaml_dict(data, slug)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ref_report = validate_profile_references(
        schema,
        slug,
        skill_exists=skill_registry.skill_exists,
        server_exists=mcp_manager.server_exists,
    )
    blocking = [f"{i.message}" for i in ref_report.errors]
    if blocking:
        raise HTTPException(status_code=400, detail={"errors": blocking})
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    from ..runtime.profile_sync_state import record_profile_after_admin_save

    record_profile_after_admin_save(file_path)
    profile_manager.invalidate()
    profile_manager.load_all_if_stale(force=True)
    return {"status": "success", "file": str(file_path), "slug": slug}


@router.delete("/profiles/{name}")
async def delete_profile(name: str):
    if not profile_manager.delete_profile(name):
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"status": "success"}


@router.get("/profiles/{name}/export")
async def export_profile_yaml(name: str):
    p = profile_manager.get_profile(name)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found")
    file_path = profile_manager.profile_yaml_path(p.slug)
    if not file_path.exists():
        # Genera al volo se manca il file fisico ma esiste in memoria
        data = {
            "name": p.name,
            "description": p.description,
            "instructions": p.instructions,
            "skills": p.skills,
            "mcp_servers": p.mcp_servers,
            "critical_skills": p.critical_skills,
        }
        content = yaml.dump(data, allow_unicode=True, sort_keys=False)
    else:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

    return Response(
        content=content,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f"attachment; filename={p.slug}.yaml"},
    )


@router.get("/profiles/export/all")
async def export_all_profiles_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in profile_manager._profiles.values():
            file_path = profile_manager.profile_yaml_path(p.slug)
            if file_path.exists():
                z.write(file_path, f"{p.slug}.yaml")
            else:
                data = {
                    "name": p.name,
                    "description": p.description,
                    "instructions": p.instructions,
                    "skills": p.skills,
                    "mcp_servers": p.mcp_servers,
                    "critical_skills": p.critical_skills,
                }
                z.writestr(
                    f"{p.slug}.yaml",
                    yaml.dump(data, allow_unicode=True, sort_keys=False),
                )
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=all_profiles.zip"},
    )


@router.post("/profiles/import-preview")
async def import_profile_preview(file: UploadFile = File(...)):
    content = await file.read()
    try:
        data = yaml.safe_load(content)
        # Assicuriamoci che i campi minimi esistano
        if not isinstance(data, dict) or "name" not in data:
            raise ValueError(
                "Il file YAML non sembra contenere un profilo valido (manca il campo 'name')"
            )
        return data
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Errore nel parsing YAML: {str(e)}"
        )


# --- SKILLS ---


@router.get("/skills")
async def list_skills(status: Optional[str] = Query(None)):
    """Elenco skill con descrizioni, tags, status e metriche view."""
    from ..learning.skill_view_metrics import view_counts

    skill_registry.reload_if_stale()
    counts = view_counts()
    result: Dict[str, Dict[str, Any]] = {}
    for name in skill_registry.get_all_names():
        meta = skill_registry.get_meta(name) or {}
        st = meta.get("status") or "verified"
        if status and st != status:
            continue
        result[name] = {
            "description": meta.get("description") or "",
            "tags": meta.get("tags") or [],
            "status": st,
            "source": meta.get("source") or "curated",
            "view_count": int(counts.get(name, 0)),
        }
    return result


@router.post("/skills/{name}/promote")
async def promote_skill(name: str):
    """Promote generated draft skill to verified (in-place frontmatter)."""
    skill_registry.reload_if_stale()
    path = skill_registry.get_skill_path(name)
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    try:
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    meta = dict(post.metadata) if post.metadata else {}
    meta["status"] = "verified"
    meta.setdefault("source", meta.get("source") or "generated")
    post.metadata = meta
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    skill_registry.reload()
    return {"status": "verified", "name": name}


@router.get("/skills/{name}")
async def get_skill(name: str):
    skill_registry.reload()
    content = skill_registry.get_skill(name)
    if content is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    meta = skill_registry.get_meta(name) or {}
    return {
        "name": name,
        "content": content,
        "metadata": {
            "description": meta.get("description", ""),
            "tags": meta.get("tags") or [],
        },
    }


@router.post("/skills")
async def save_skill(s: SkillUpdate):
    existing_path = skill_registry.get_skill_path(s.name)
    if existing_path:
        rel_path = None
        for base_dir in (
            skill_registry.curated_dir,
            skill_registry.curated_fallback_dir,
            skill_registry.generated_dir,
        ):
            try:
                rel_path = existing_path.relative_to(base_dir)
                break
            except ValueError:
                continue
        if rel_path:
            file_path = skill_registry.curated_dir / rel_path
        else:
            file_path = skill_registry.curated_dir / f"{s.name}.md"
    else:
        file_path = skill_registry.curated_dir / f"{s.name}.md"

    os.makedirs(file_path.parent, exist_ok=True)

    # Parse potential existing frontmatter in the input content
    try:
        post = frontmatter.loads(s.content)
        content_body = post.content or ""
        meta = dict(post.metadata) if post.metadata else {}
    except Exception:
        content_body = s.content
        meta = {}

    # Get existing metadata from registry
    existing_meta = skill_registry.get_meta(s.name)
    merged_meta = {}
    if existing_meta:
        merged_meta.update(existing_meta)

    # Merge metadata passed explicitly in the request
    if s.metadata:
        merged_meta.update(s.metadata)

    # Update with parsed meta (which takes precedence)
    merged_meta.update(meta)

    # Ensure minimal keys
    if "name" not in merged_meta:
        merged_meta["name"] = s.name
    if "description" not in merged_meta:
        merged_meta["description"] = s.name.replace("_", " ").title()
    if "tags" not in merged_meta:
        merged_meta["tags"] = []
    if "status" not in merged_meta:
        merged_meta["status"] = "verified"
    if "source" not in merged_meta:
        merged_meta["source"] = "curated"
    if "version" not in merged_meta:
        merged_meta["version"] = 1

    if "tags" in merged_meta and isinstance(merged_meta["tags"], list):
        merged_meta["tags"] = FlowList(merged_meta["tags"])

    new_post = frontmatter.Post(content=content_body, **merged_meta)
    serialized = frontmatter.dumps(new_post)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(serialized)

    skill_registry.reload()
    return {"status": "success"}


@router.delete("/skills/{name}")
async def delete_skill(name: str):
    from ..agent_profile import profile_manager

    # Ricarica e verifica utilizzo nei profili
    profile_manager.load_all()
    referencing_profiles = []
    for p in profile_manager._profiles.values():
        if name in p.skills or (p.critical_skills and name in p.critical_skills):
            referencing_profiles.append(p.name)

    if referencing_profiles:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "skill_in_use",
                "message": f"Impossibile eliminare la skill. È in uso nei seguenti profili: {', '.join(referencing_profiles)}",
                "profiles": referencing_profiles,
            },
        )

    if not skill_registry.delete_skill(name):
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"status": "success"}


@router.get("/skills/{name}/export")
async def export_skill_md(name: str):
    skill_registry.reload()
    path = skill_registry.get_skill_path(name)

    if path and path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Could not read skill file: {e}"
            )
    else:
        # Fallback if file not found physically, serialize in memory
        body = skill_registry.get_skill_full(name)
        if body is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        meta = skill_registry.get_meta(name) or {}
        new_post = frontmatter.Post(content=body, **meta)
        content = frontmatter.dumps(new_post)

    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={name}.md"},
    )


@router.get("/skills/export/all")
async def export_all_skills_zip():
    buf = io.BytesIO()
    skill_registry.reload()
    base_path = Path("config/skills").resolve()
    with zipfile.ZipFile(buf, "w") as z:
        seen: set[str] = set()
        for name in skill_registry.get_all_names():
            entry = skill_registry._skills.get(name) or {}
            path = Path(entry.get("path") or "")
            if not path.is_file() or str(path) in seen:
                continue
            seen.add(str(path))
            try:
                arcname = path.relative_to(base_path)
            except ValueError:
                arcname = Path(name) / path.name
            z.write(path, str(arcname))
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=all_skills.zip"},
    )


@router.post("/skills/import-preview")
async def import_skill_preview(file: UploadFile = File(...)):
    filename = file.filename or "imported_skill.md"
    if not filename.endswith(".md"):
        raise HTTPException(
            status_code=400, detail="Only .md files are supported for preview."
        )

    content = await file.read()
    try:
        text_content = content.decode("utf-8")
        name = filename.replace(".md", "")

        try:
            post = frontmatter.loads(text_content)
            content_body = post.content or ""
            metadata = dict(post.metadata) if post.metadata else {}
        except Exception:
            content_body = text_content
            metadata = {}

        return {"name": name, "content": content_body, "metadata": metadata}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Errore nella lettura del file: {str(e)}"
        )


# --- MODULAR MCP HUB ---


@router.get("/registry")
async def get_registry():
    mcp_manager.load_registry()
    res = {}
    for name, cfg in mcp_manager._registry.items():
        c = dict(cfg)
        c["is_base"] = name in mcp_manager._registry_base
        res[name] = c
    return res


@router.get("/native-tools")
async def get_native_tools():
    from ..runtime.native_tools.registry_io import load_merged_native_tool_registry

    return load_merged_native_tool_registry()


@router.get("/mcp/connector-catalog")
async def mcp_connector_catalog():
    """Curated enterprise connectors (YAML): docs + registry hints; servers are third-party."""
    return load_mcp_connector_catalog()


class McpIntegrationCreate(BaseModel):
    server_slug: str
    display_name: str
    description: Optional[str] = None
    icon_url: Optional[str] = None
    category: Optional[str] = None
    is_enabled_for_users: bool = False
    requires_user_credentials: bool = False
    credential_mode: str = "none"
    credential_schema: Optional[List[Dict[str, Any]]] = None
    oauth_config: Optional[Dict[str, Any]] = None
    schema_override: bool = False
    user_may_disable: bool = True


class McpIntegrationUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon_url: Optional[str] = None
    category: Optional[str] = None
    is_enabled_for_users: Optional[bool] = None
    requires_user_credentials: Optional[bool] = None
    credential_mode: Optional[str] = None
    credential_schema: Optional[List[Dict[str, Any]]] = None
    oauth_config: Optional[Dict[str, Any]] = None
    schema_override: bool = False
    apply_suggested_env: bool = False
    user_may_disable: Optional[bool] = None


class McpIntegrationAdviseBody(BaseModel):
    server_slug: Optional[str] = None
    connector_id: Optional[str] = None
    admin_message: Optional[str] = None


def _mcp_integration_to_dict(
    r: McpServerConfig, *, in_registry: bool
) -> Dict[str, Any]:
    return {
        "id": r.id,
        "server_slug": r.server_slug,
        "display_name": r.display_name,
        "description": r.description,
        "icon_url": r.icon_url,
        "category": r.category,
        "is_enabled_for_users": r.is_enabled_for_users,
        "requires_user_credentials": r.requires_user_credentials,
        "credential_mode": getattr(r, "credential_mode", None) or "none",
        "aion_connector_id": getattr(r, "aion_connector_id", None),
        "user_may_disable": bool(getattr(r, "user_may_disable", True)),
        "credential_schema": json.loads(r.credential_schema_json or "[]"),
        "oauth_config": json.loads(r.oauth_config_json or "{}"),
        "is_in_registry": in_registry,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


@router.get("/mcp-integrations")
async def admin_list_mcp_integrations():
    """Lista configurazioni integrazione MCP + server nel registry senza riga DB."""
    mcp_manager.load_registry()
    registry_servers = mcp_manager.get_all_servers()
    async with get_async_session_maker()() as session:
        rows = (await session.execute(select(McpServerConfig))).scalars().all()
    configured_slugs = {r.server_slug for r in rows}
    return {
        "integrations": [
            _mcp_integration_to_dict(r, in_registry=r.server_slug in registry_servers)
            for r in rows
        ],
        "registry_servers_not_configured": [
            s for s in registry_servers if s not in configured_slugs
        ],
    }


@router.post("/mcp-integrations")
async def admin_create_mcp_integration(body: McpIntegrationCreate):
    new_id: str
    async with get_async_session_maker()() as session:
        exists = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug == body.server_slug
                    )
                )
            )
            .scalars()
            .first()
        )
        if exists:
            raise HTTPException(
                status_code=409,
                detail="Integration with this server_slug already exists",
            )
        mode = (
            body.credential_mode
            if body.credential_mode in ("none", "org_shared", "per_user")
            else "none"
        )
        req_creds = (
            body.requires_user_credentials
            if body.requires_user_credentials
            else mode == "per_user"
        )
        new_cfg = McpServerConfig(
            id=new_uuid7_str(),
            server_slug=body.server_slug,
            display_name=body.display_name,
            description=body.description,
            icon_url=body.icon_url,
            category=body.category,
            is_enabled_for_users=body.is_enabled_for_users,
            requires_user_credentials=req_creds,
            credential_mode=mode,
            user_may_disable=body.user_may_disable,
            credential_schema_json=json.dumps(body.credential_schema or []),
            oauth_config_json=json.dumps(body.oauth_config or {}),
        )
        session.add(new_cfg)
        await session.commit()
        new_id = new_cfg.id
    return {"ok": True, "id": new_id}


@router.patch("/mcp-integrations/{server_slug}")
async def admin_update_mcp_integration(server_slug: str, body: McpIntegrationUpdate):
    from ..mcp_integration_sync import (
        credential_schema_from_connector,
        load_mcp_connector_catalog,
        merge_suggested_env_into_registry,
        resolve_connector_row_for_mcp_server,
    )

    mcp_manager.load_registry()
    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug == server_slug
                    )
                )
            )
            .scalars()
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Integration not found")
        if body.display_name is not None:
            row.display_name = body.display_name
        if body.description is not None:
            row.description = body.description
        if body.icon_url is not None:
            row.icon_url = body.icon_url
        if body.category is not None:
            row.category = body.category
        if body.is_enabled_for_users is not None:
            row.is_enabled_for_users = body.is_enabled_for_users
        if body.credential_mode is not None and body.credential_mode in (
            "none",
            "org_shared",
            "per_user",
        ):
            row.credential_mode = body.credential_mode
            if body.requires_user_credentials is None:
                row.requires_user_credentials = body.credential_mode == "per_user"
        if body.requires_user_credentials is not None:
            row.requires_user_credentials = body.requires_user_credentials
        if body.credential_schema is not None:
            connector_id = row.aion_connector_id
            if not body.schema_override and connector_id:
                catalog = load_mcp_connector_catalog()
                cfg = mcp_manager._registry.get(server_slug) or {}
                conn = resolve_connector_row_for_mcp_server(server_slug, cfg, catalog)
                row.credential_schema_json = json.dumps(
                    credential_schema_from_connector(conn)
                )
            else:
                row.credential_schema_json = json.dumps(body.credential_schema)
        if body.oauth_config is not None:
            row.oauth_config_json = json.dumps(body.oauth_config)
        if body.user_may_disable is not None:
            row.user_may_disable = body.user_may_disable
        row.updated_at = datetime.now(timezone.utc)
        mode_after = row.credential_mode or "none"
        await session.commit()

    if body.apply_suggested_env and mode_after in ("per_user", "org_shared"):
        schema_for_env = None
        if body.schema_override and body.credential_schema is not None:
            schema_for_env = body.credential_schema
        merge_suggested_env_into_registry(
            server_slug,
            mode_after,
            credential_schema=schema_for_env,
        )

    return {"ok": True}


@router.post("/mcp-integrations/sync-from-registry")
async def admin_sync_mcp_integrations_from_registry(server_slug: Optional[str] = None):
    from ..mcp_integration_sync import (
        sync_all_mcp_server_configs_from_registry,
        sync_mcp_server_config_from_registry,
    )

    if server_slug:
        row = await sync_mcp_server_config_from_registry(server_slug)
        if not row:
            raise HTTPException(status_code=404, detail="Server not in registry")
        return {"ok": True, "server_slug": server_slug}
    return {"ok": True, **(await sync_all_mcp_server_configs_from_registry())}


@router.get("/mcp-integrations/{server_slug}/preview")
async def admin_preview_mcp_integration(
    server_slug: str, credential_mode: Optional[str] = None
):
    from ..mcp_integration_sync import build_integration_preview

    preview = build_integration_preview(server_slug, credential_mode=credential_mode)
    if not preview.get("ok"):
        raise HTTPException(status_code=404, detail=preview.get("error", "Not found"))
    conn = preview.pop("connector", None)
    if conn:
        preview["connector_id"] = conn.get("id")
        preview["connector_title"] = conn.get("title")
        preview["integration_hints"] = conn.get("integration_hints")
        preview["official_doc_url"] = conn.get("official_doc_url")
        preview["agent_guidance"] = conn.get("agent_guidance")
    return preview


@router.post("/mcp-integrations/advise")
async def admin_advise_mcp_integration(body: McpIntegrationAdviseBody):
    from ..mcp_integration_sync import (
        build_integration_preview,
        load_mcp_connector_catalog,
    )

    _log = logging.getLogger("aion.admin.advise")

    slug = (body.server_slug or "").strip()
    if not slug and body.connector_id:
        try:
            catalog = load_mcp_connector_catalog()
            for c in catalog.get("connectors") or []:
                if isinstance(c, dict) and c.get("id") == body.connector_id:
                    hints = c.get("mcp_name_hints") or [body.connector_id]
                    slug = str(hints[0]) if hints else body.connector_id
                    break
        except Exception as e:
            _log.warning("Errore risoluzione connector_id: %s", e)
    if not slug:
        raise HTTPException(
            status_code=400, detail="server_slug or connector_id required"
        )

    # --- build_integration_preview con error handling ---
    preview: dict = {}
    try:
        preview = build_integration_preview(slug)
    except Exception as e:
        _log.exception("build_integration_preview fallita per %s", slug)
        preview = {"ok": False, "error": str(e)}
    if not preview.get("ok"):
        raise HTTPException(
            status_code=404,
            detail=preview.get("error", f"Server '{slug}' not in registry"),
        )

    mode: str = preview.get("credential_mode") or "none"
    schema: list = preview.get("credential_schema") or []
    connector: dict = preview.get("connector") or {}
    current_env: dict = preview.get("current_env") or {}
    warnings_list: list = preview.get("warnings") or []
    discovery_info: dict = preview.get("discovery") or {}

    yaml_env = (
        preview.get(
            "suggested_env_per_user"
            if mode == "per_user"
            else "suggested_env_org_shared"
        )
        or {}
    )
    env_yaml = (
        "\n".join(f'    {k}: "{v}"' for k, v in yaml_env.items())
        if yaml_env
        else "    # nessuna"
    )

    # --- AI analysis via LLM (async) ---
    steps_md = ""
    llm_used = False
    llm_error: str | None = None
    llm_available = False
    try:
        from src.runtime.llm_adapter import resolve_llm_endpoint

        llm_url, _ = resolve_llm_endpoint()
        llm_available = bool(llm_url)
    except Exception:
        pass

    if llm_available:
        try:
            _log.info(
                "Chiamata LLM advise per %s (mode=%s, schema=%d campi)",
                slug,
                mode,
                len(schema),
            )
            steps_md, llm_error = await _call_llm_advise_async(
                slug,
                mode,
                schema,
                connector,
                current_env,
                warnings_list,
                body.admin_message if hasattr(body, "admin_message") else None,
                discovery_info=discovery_info,
            )
            if steps_md and len(steps_md.strip()) > 50:
                llm_used = True
                _log.info("LLM advise OK per %s (%d caratteri)", slug, len(steps_md))
            else:
                llm_used = False
                if not llm_error:
                    llm_error = "Risposta LLM troppo breve o vuota"
                _log.warning("LLM advise vuota/breve per %s: %s", slug, llm_error)
        except Exception as e:
            llm_error = str(e)
            steps_md = ""
            _log.exception("LLM advise fallita per %s", slug)

    # Fallback: report ricco da discovery (wizard completo anche senza LLM)
    if not steps_md:
        steps_md = _build_discovery_advise_markdown(slug, preview, llm_error)

    # --- Estrai il JSON dalla risposta AI o dal fallback discovery ---
    ai_config = _parse_ai_json_from_markdown(steps_md)

    # Costruisci config_suggestion: prioritizza AI, fallback discovery/preview
    if ai_config:
        ai_mode = ai_config.get("credential_mode", mode)
        ai_env = ai_config.get("env_variables") or {}
        ai_schema = ai_config.get("credential_schema") or schema

        # Normalizza i placeholder generici SLUG → slug reale
        slug_upper = slug.upper().replace("-", "_")
        normalized_env = {}
        for k, v in ai_env.items():
            if isinstance(v, str) and "AION_USER_SLUG__" in v:
                v = v.replace("AION_USER_SLUG__", f"AION_USER_{slug_upper}__")
            normalized_env[k] = v
        ai_env = normalized_env

        config_suggestion = {
            "credential_mode": ai_mode,
            "requires_user_credentials": ai_mode == "per_user",
            "is_enabled_for_users": ai_config.get(
                "is_enabled_for_users", ai_mode != "none"
            ),
            "user_may_disable": ai_config.get(
                "user_may_disable", ai_mode == "per_user"
            ),
            "apply_suggested_env": ai_config.get(
                "apply_suggested_env", ai_mode in ("per_user", "org_shared")
            ),
            "suggested_env": ai_env,
            "credential_schema": ai_schema,
            "warnings": ai_config.get("warnings") or warnings_list,
            "rationale": ai_config.get("rationale", ""),
            "_source": "ai",
        }
        # Se l'AI ha cambiato la modalità, aggiorna anche i valori di ritorno
        if ai_mode != mode:
            mode = ai_mode
            yaml_env = ai_env
            schema = ai_schema
    else:
        config_suggestion = _config_suggestion_from_preview(slug, preview)
        if llm_error:
            config_suggestion["warnings"] = list(
                config_suggestion.get("warnings") or []
            ) + [f"Analisi LLM: {llm_error}"]

    config_suggestion = _reconcile_config_with_discovery(
        config_suggestion, slug, preview
    )
    mode = config_suggestion.get("credential_mode", mode)
    schema = config_suggestion.get("credential_schema") or schema
    yaml_env = config_suggestion.get("suggested_env") or yaml_env
    env_yaml = (
        "\n".join(f'    {k}: "{v}"' for k, v in yaml_env.items())
        if yaml_env
        else "    # nessuna"
    )

    return {
        "server_slug": slug,
        "credential_mode": mode,
        "credential_schema": schema,
        "suggested_env": yaml_env,
        "suggested_registry_env_yaml": f"env:\n{env_yaml}",
        "warnings": config_suggestion.get("warnings") or warnings_list,
        "steps_markdown": steps_md,
        "llm_used": llm_used,
        "llm_error": llm_error,
        "config_suggestion": config_suggestion,
        "discovery": discovery_info,
    }


def _parse_ai_json_from_markdown(markdown_text: str) -> dict | None:
    """Estrae il primo blocco JSON valido da una risposta markdown dell'AI.
    Cerca pattern ```json ... ``` o { ... } direttamente nel testo.
    """
    import json as _json
    import re as _re
    import logging as _logging

    _log = _logging.getLogger("aion.admin.advise")
    if not markdown_text or not isinstance(markdown_text, str):
        return None

    # Strategia 1: cerca blocco ```json ... ```
    json_block = _re.search(r"```json\s*\n(.*?)\n```", markdown_text, _re.DOTALL)
    if json_block:
        try:
            return _json.loads(json_block.group(1))
        except _json.JSONDecodeError:
            pass

    # Strategia 2: cerca credential_mode e prova a estrarre JSON con parentesi bilanciate
    # (gestisce JSON annidati come credential_schema array di oggetti, env_variables nested)
    for cred_match in _re.finditer(
        r'"credential_mode"\s*:\s*"(?:none|org_shared|per_user)"',
        markdown_text,
    ):
        # Cerca la parentesi graffa di apertura più vicina prima del match
        start = markdown_text.rfind("{", 0, cred_match.start())
        if start < 0:
            continue
        # Cerca la parentesi di chiusura bilanciata
        depth = 0
        end = -1
        for i in range(start, min(len(markdown_text), start + 8000)):
            if markdown_text[i] == "{":
                depth += 1
            elif markdown_text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end > start:
            try:
                return _json.loads(markdown_text[start : end + 1])
            except _json.JSONDecodeError:
                continue

    # Strategia 3: cerca qualsiasi JSON object semplice che sembri valido
    for match in _re.finditer(r"\{[^{}]*\}", markdown_text, _re.DOTALL):
        try:
            obj = _json.loads(match.group())
            if "credential_mode" in obj:
                return obj
        except _json.JSONDecodeError:
            continue

    _log.info("_parse_ai_json_from_markdown: nessun JSON valido trovato")
    return None


def _config_suggestion_from_preview(slug: str, preview: dict) -> dict:
    """Config strutturata da discovery/preview (wizard funziona anche senza LLM)."""
    from ..mcp_integration_sync import (
        suggest_registry_env_for_org_shared,
        suggest_registry_env_for_per_user,
    )

    mode = preview.get("credential_mode") or "none"
    schema = preview.get("credential_schema") or []
    if mode == "per_user":
        suggested_env = preview.get(
            "suggested_env_per_user"
        ) or suggest_registry_env_for_per_user(slug, schema)
    elif mode == "org_shared":
        suggested_env = preview.get(
            "suggested_env_org_shared"
        ) or suggest_registry_env_for_org_shared(schema)
    else:
        suggested_env = {}
    return {
        "credential_mode": mode,
        "requires_user_credentials": mode == "per_user",
        "is_enabled_for_users": mode != "none",
        "user_may_disable": mode == "per_user",
        "apply_suggested_env": mode in ("per_user", "org_shared"),
        "suggested_env": suggested_env,
        "credential_schema": schema,
        "warnings": list(preview.get("warnings") or []),
        "rationale": "Generato da rilevamento automatico (README/sorgenti/registry).",
        "_source": "discovery",
    }


def _build_discovery_advise_markdown(
    slug: str, preview: dict, llm_error: str | None = None
) -> str:
    """Report wizard quando l'LLM non risponde in tempo."""
    mode = preview.get("credential_mode") or "none"
    schema = preview.get("credential_schema") or []
    discovery = preview.get("discovery") or {}
    lines = [
        f"# Configurazione MCP: `{slug}`",
        "",
        "## Riepilogo (automatico)",
        f"Server installato in `mcp_servers/`. Modalità credenziali rilevata: **{mode}**.",
        "",
    ]
    if discovery.get("env_keys"):
        lines.append("### Variabili rilevate")
        for k in discovery.get("env_keys") or []:
            lines.append(f"- `{k}`")
        lines.append("")
    if schema:
        lines.append("### Schema credenziali")
        for f in schema:
            req = "obbligatorio" if f.get("required") else "opzionale"
            lines.append(f"- `{f.get('key')}` ({f.get('type', 'text')}, {req})")
        lines.append("")
    if mode == "per_user":
        lines.extend(
            [
                "## Passi admin",
                "1. Abilita «Disponibile in chat».",
                "2. Applica env suggerito (placeholder `${AION_USER_*}`).",
                "3. Aggiungi lo slug al profilo agente (`mcp_servers`).",
                "4. Gli utenti compilano **Le mie integrazioni** in chat-ui.",
            ]
        )
    elif mode == "org_shared":
        lines.extend(
            [
                "## Passi admin",
                "1. Imposta i secret in `.env` host o nel form Hub.",
                "2. Applica env suggerito nel registry.",
                "3. Abilita chat e profilo agente.",
            ]
        )
    else:
        lines.append(
            "Nessuna credenziale env rilevata; verifica README (config file vs env)."
        )
    if llm_error:
        lines.extend(["", f"---\n⚠️ Analisi LLM non disponibile: {llm_error}"])
    cfg = _config_suggestion_from_preview(slug, preview)
    import json as _json

    lines.extend(
        [
            "",
            "## Configurazione JSON",
            "```json",
            _json.dumps(cfg, indent=2, ensure_ascii=False),
            "```",
        ]
    )
    return "\n".join(lines)


def _reconcile_config_with_discovery(config: dict, slug: str, preview: dict) -> dict:
    """Se la discovery trova env di autenticazione, non lasciare credential_mode=none dall'LLM."""
    from ..mcp_integration_sync import suggest_registry_env_for_per_user

    discovery = preview.get("discovery") or {}
    if not discovery.get("has_env_auth"):
        return config
    preview_schema = preview.get("credential_schema") or []
    preview_mode = preview.get("credential_mode") or "none"
    out = dict(config)
    if (
        out.get("credential_mode") in ("none", "org_shared")
        and preview_mode == "per_user"
    ):
        out["credential_mode"] = "per_user"
        out["requires_user_credentials"] = True
        out["apply_suggested_env"] = True
        out["is_enabled_for_users"] = out.get("is_enabled_for_users", True)
        if not out.get("credential_schema"):
            out["credential_schema"] = preview_schema
        if not out.get("suggested_env") and preview_schema:
            out["suggested_env"] = suggest_registry_env_for_per_user(
                slug, preview_schema
            )
        warns = list(out.get("warnings") or [])
        warns.append(
            "Correzione automatica: rilevate variabili d'ambiente per credenziali nel server; "
            "modalità «none» non applicabile (il README può anche citare config.toml)."
        )
        out["warnings"] = warns
        src = str(out.get("_source") or "ai")
        out["_source"] = src if "discovery" in src else f"{src}+discovery"
    return out


async def _call_llm_advise_async(
    slug: str,
    mode: str,
    schema: list,
    connector: dict,
    current_env: dict,
    warnings: list,
    admin_message: str | None = None,
    *,
    discovery_info: dict | None = None,
) -> tuple[str, str | None]:
    """Chiama l'LLM in modo asincrono per un'analisi approfondita del server MCP.

    Returns: (markdown_response, error_string_or_None)
    """
    import json as _json
    import httpx
    import logging as _logging

    _log = _logging.getLogger("aion.admin.advise")

    try:
        from src.runtime.llm_adapter import resolve_llm_credentials

        base, model, token = resolve_llm_credentials()
        if not base.endswith("/v1"):
            base = base + "/v1" if "/v1" not in base else base.split("/v1")[0] + "/v1"
        url = base.rstrip("/") + "/chat/completions"
    except Exception as e:
        return "", f"Errore costruzione URL LLM: {e}"

    from ..mcp_server_files import read_mcp_server_files

    server_files_context = read_mcp_server_files(slug)
    connector_info = ""
    if connector:
        try:
            connector_info = _json.dumps(
                {
                    "title": connector.get("title", ""),
                    "category": connector.get("category", ""),
                    "credential_fields": connector.get("credential_fields", []),
                },
                indent=2,
            )
        except Exception:
            pass

    system_prompt = (
        "Sei un esperto di configurazione MCP (Model Context Protocol) per AION Agent. "
        "Analizza i FILE REALI del server MCP (README.md, package.json, codice sorgente) "
        "che ti vengono forniti e produci una guida passo-passo in italiano per l'amministratore.\n\n"
        "REGOLE FONDAMENTALI:\n"
        "- Leggi ATTENTAMENTE il README.md: contiene le istruzioni di setup e le variabili d'ambiente richieste\n"
        "- Cerca nel README sezioni come 'Setup', 'Configuration', 'Environment Variables', '.env'\n"
        "- Se il README mostra variabili come EMAIL_USER, EMAIL_PASSWORD, API_KEY, TOKEN → "
        "il server richiede credenziali PER UTENTE (credential_mode=per_user)\n"
        "- Se il README non menziona credenziali ma richiede config generiche → credential_mode=org_shared\n"
        "- Se il README documenta SOLO config.toml/XDG senza alcuna variabile env per account → credential_mode=none\n"
        "- IMPORTANTE: molti server documentano config.toml E anche env (es. MCP_EMAIL_ADDRESS, EMAIL_USER, "
        "process.env.API_KEY). In quel caso preferisci per_user con le variabili env, non none.\n"
        "- Elenca TUTTE le variabili trovate, con tipo (password per token/secret, text per config)\n\n"
        "Dopo l'analisi, includi SEMPRE un blocco JSON con la configurazione:\n"
        "```json\n{\n"
        '  "credential_mode": "none|org_shared|per_user",\n'
        '  "requires_user_credentials": true/false,\n'
        '  "is_enabled_for_users": true/false,\n'
        '  "user_may_disable": true/false,\n'
        '  "apply_suggested_env": true/false,\n'
        '  "env_variables": {\n'
        '    "NOME_VAR": "${AION_USER_SLUG__NOME_VAR}" (se per_user) oppure "${NOME_VAR}" (se org_shared),\n'
        '    "...": "..."\n'
        "  },\n"
        '  "credential_schema": [\n'
        '    {"key": "EMAIL_USER", "label": "Email", "type": "text", "required": true},\n'
        '    {"key": "EMAIL_PASSWORD", "label": "Password", "type": "password", "required": true}\n'
        "  ],\n"
        '  "rationale": "spiegazione del perché questa modalità"\n'
        "}\n```"
    )

    user_prompt = (
        f"## Server MCP da analizzare\n\n"
        f"- **Slug:** `{slug}`\n"
        f"- **Modalità credenziali rilevata automaticamente:** `{mode}`\n"
        f"- **Schema credenziali dal catalogo:** {len(schema)} campi\n"
    )
    if server_files_context:
        user_prompt += (
            f"\n### File del server MCP (fonte primaria)\n{server_files_context}\n"
        )
    if connector_info:
        user_prompt += f"\n### Connettore catalogato\n```json\n{connector_info}\n```\n"
    if schema:
        for f in schema:
            try:
                req = " (obbligatorio)" if f.get("required") else " (opzionale)"
                user_prompt += f"- `{f.get('key', '?')}`: {f.get('label', '?')} — tipo: {f.get('type', 'text')}{req}\n"
            except Exception:
                pass
    if current_env:
        try:
            safe_env = {}
            for k, v in current_env.items():
                s = str(v) if v is not None else ""
                safe_env[k] = s[:80] + "..." if len(s) > 80 else s
            user_prompt += f"\n### Variabili d'ambiente attuali\n```json\n{_json.dumps(safe_env, indent=2, ensure_ascii=False)}\n```\n"
        except Exception:
            pass
    if warnings:
        user_prompt += (
            "\n### Avvertenze automatiche\n"
            + "\n".join(f"- ⚠ {w}" for w in warnings)
            + "\n"
        )
    if discovery_info:
        try:
            user_prompt += (
                f"\n### Rilevamento automatico AION (pre-LLM)\n"
                f"- Modalità suggerita: `{discovery_info.get('credential_mode_hint', 'none')}`\n"
                f"- Env rilevate: {', '.join(discovery_info.get('env_keys') or []) or '(nessuna)'}\n"
                f"- Fonti: {', '.join(discovery_info.get('sources') or [])}\n"
                f"- Solo file config (TOML/XDG): {discovery_info.get('config_file_auth')}\n"
                f"- Auth via env: {discovery_info.get('has_env_auth')}\n"
                f"Usa questo blocco se coerente con i file; correggi l'LLM se propone «none» ma ci sono env di login.\n"
            )
        except Exception:
            pass
    if admin_message:
        user_prompt += f"\n### Nota dell'amministratore\n{admin_message}\n"

    user_prompt += (
        "\n## Istruzioni\n"
        "Analizza i file del server MCP (README.md, package.json, codice sorgente) e produci:\n"
        "1. **Riepilogo:** cosa fa questo server, basandoti sui file reali letti\n"
        "2. **Modalità credenziali:** `none`/`org_shared`/`per_user` spiegando perché. "
        "Se il README mostra variabili come EMAIL_USER, EMAIL_PASSWORD, IMAP_HOST, "
        "il server richiede credenziali → modalità `per_user` (ogni utente ha le proprie)\n"
        "3. **Variabili necessarie:** elenca TUTTE le variabili d'ambiente trovate nei file "
        "(README.md, .env.example, codice). Per ciascuna indica: nome, tipo (sensibile/configurazione), "
        "obbligatorietà, descrizione. Cerca pattern come `process.env.XXX`, `dotenv`, sezioni `.env` nel README\n"
        "4. **Configurazione admin:** passi concreti da eseguire in MCP Hub per questo server specifico\n"
        "5. **Impatto utenti:** cosa vedranno in chat-ui\n"
        "6. **Blocco JSON** con la configurazione esatta\n"
    )

    try:
        # Advise: cap token basso (risposta strutturata breve). Chat usa AION_CHAT_MAX_TOKENS.
        advise_cap = int(os.getenv("AION_MCP_ADVISE_MAX_TOKENS", "2048"))
        chat_cap = int(os.getenv("AION_CHAT_MAX_TOKENS", "4096"))
        max_tokens = min(advise_cap, chat_cap) if chat_cap > 0 else advise_cap
        advise_timeout = float(
            os.getenv("AION_MCP_ADVISE_TIMEOUT", os.getenv("AION_LLM_TIMEOUT", "120"))
        )
        # Disabilita reasoning su advise: riduce latenza e evita content=null su modelli
        # thinking. Usa enable_thinking=False (vLLM-native) invece di reasoning_effort=none
        # (OpenAI compat, non sempre supportato da backend come vLLM/Qwen).
        # Env var AION_MCP_ADVISE_DISABLE_REASONING (default: 1) — imposta a 0 per abilitare reasoning.
        _disable_reasoning = (
            os.getenv("AION_MCP_ADVISE_DISABLE_REASONING", "1").strip().lower()
        )
        generation_kwargs = {
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        if _disable_reasoning not in ("0", "false", "no", "off"):
            generation_kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False}
            }

        from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper
        from haystack.dataclasses import ChatMessage
        from haystack.utils import Secret

        generator = LiteLLMChatGeneratorWrapper(
            model=model,
            api_base_url=base,
            api_key=Secret.from_token(token),
            timeout=advise_timeout,
            generation_kwargs=generation_kwargs,
        )

        chat_messages = [
            ChatMessage.from_system(system_prompt),
            ChatMessage.from_user(user_prompt),
        ]



        res = await generator.run_async(messages=chat_messages)
        if not res or "replies" not in res or not res["replies"]:
            return "", "Nessuna risposta ricevuta dall'LLM"

        reply = res["replies"][0]
        content = reply.text
        meta = reply.meta or {}
        reasoning = meta.get("reasoning") or meta.get("reasoning_content") or ""

        if content is None or len(content.strip()) < 50:
            # Fallback reasoning
            if isinstance(reasoning, str) and len(reasoning.strip()) > 100:

                import re as _re

                json_block = _re.search(
                    r"```json\s*\n(.*?)\n```", reasoning, _re.DOTALL
                )
                if json_block:
                    return json_block.group(0).strip(), None

                cred_match = _re.search(
                    r'"credential_mode"\s*:\s*"(?:none|org_shared|per_user)"', reasoning
                )
                if cred_match:
                    start = reasoning.rfind("{", 0, cred_match.start())
                    if start >= 0:
                        depth = 0
                        for i in range(start, min(len(reasoning), start + 8000)):
                            if reasoning[i] == "{":
                                depth += 1
                            elif reasoning[i] == "}":
                                depth -= 1
                                if depth == 0:
                                    candidate = reasoning[start : i + 1]
                                    try:
                                        _json.loads(candidate)
                                        return candidate.strip(), None
                                    except _json.JSONDecodeError:
                                        pass
                                    break

                # fallback ultimo terzo del reasoning
                third = max(len(reasoning) // 3, 500)
                return reasoning[-third:].strip(), None

            # Riprova con max_tokens incrementato se cut-off
            finish = meta.get("finish_reason", "?")
            if finish == "length" and max_tokens < 8192:
                _log.warning(
                    "LLM content corto (finish=length), riprovo con max_tokens=8192 e reasoning disabilitato"
                )
                generation_kwargs["max_tokens"] = 8192
                generation_kwargs["extra_body"] = {
                    "chat_template_kwargs": {"enable_thinking": False}
                }

                generator2 = LiteLLMChatGeneratorWrapper(
                    model=model,
                    api_base_url=base,
                    api_key=Secret.from_token(token),
                    timeout=90.0,
                    generation_kwargs=generation_kwargs,
                )
                res2 = await generator2.run_async(messages=chat_messages)
                if res2 and "replies" in res2 and res2["replies"]:
                    content2 = res2["replies"][0].text
                    if isinstance(content2, str) and len(content2.strip()) > 50:
                        return content2.strip(), None

            return "", f"LLM non ha prodotto contenuto valido (finish_reason={finish})."

        return content.strip(), None

    except Exception as e:
        _log.exception("LLM advise fallita per %s", slug)
        return "", str(e)


@router.post("/mcp-integrations/{server_slug}/apply-suggested-env")
async def admin_apply_suggested_env(
    server_slug: str, credential_mode: str = "per_user"
):
    from ..mcp_integration_sync import apply_integration_config

    if credential_mode not in ("per_user", "org_shared"):
        raise HTTPException(
            status_code=400, detail="credential_mode must be per_user or org_shared"
        )
    result = await apply_integration_config(
        server_slug,
        credential_mode=credential_mode,
        apply_suggested_env=True,
        sync_db=False,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Failed"))
    return result


@router.delete("/mcp-integrations/{server_slug}")
async def admin_delete_mcp_integration(server_slug: str):
    async with get_async_session_maker()() as session:
        await session.execute(
            delete(McpServerConfig).where(McpServerConfig.server_slug == server_slug)
        )
        await session.commit()
    return {"ok": True}


@router.get("/market/search")
async def search_market(q: str = ""):
    """Searches across integrated MCP marketplaces."""
    return hub_aggregator.search_all(q)


# --- SECURITY & TRUST ---


@router.post("/security/trust")
async def add_trust(req: TrustRequest):
    """Mark a path as trusted."""
    from ..security.trust_manager import trust_manager

    await trust_manager.add_trust(req.path)
    return {"status": "success"}


@router.delete("/security/trust")
async def remove_trust(path: str):
    """Remove trust from a path."""
    from ..security.trust_manager import trust_manager

    await trust_manager.remove_trust(path)
    return {"status": "success"}


# --- MEMORY MANAGEMENT ---


@router.get("/memory/queries")
async def get_verified_queries(limit: int = 100):
    """List most recent queries from QueryMemory."""
    from ..query_memory import memory

    return await memory.get_recent(limit=limit)


@router.post("/stm/consolidate")
async def stm_consolidate_alias(body: StmConsolidateBody):
    """STM → LTM batch consolidation (alias path per piano)."""
    from ..memory import stm_consolidator
    from ..memory.ltm_audit import append_ltm_audit

    append_ltm_audit(
        "stm_consolidate",
        {
            "session_id": body.session_id,
            "profile_name": body.profile_name,
            "user_id": body.user_id,
        },
    )
    return await stm_consolidator.consolidate(
        body.session_id,
        body.profile_name,
        body.user_id,
        prune_after=body.prune_after,
    )


@router.post("/memory/queries/{id}/verify")
async def verify_query(id: int):
    """Mark a query as verified manually."""
    from ..query_memory import memory

    success = await memory.update_entry(id, is_verified=True)
    return {"status": "success" if success else "failed"}


@router.delete("/memory/queries/{entry_id}")
async def delete_query(entry_id: int):
    """Delete a query from memory."""
    from ..query_memory import memory

    if await memory.delete_entry(entry_id):
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Entry not found")


@router.get("/memory/facts")
async def get_mempalace_facts(query: str = ""):
    """Retrieves project-specific semantic facts from Mempalace."""
    try:
        # Build parameters for the mempalace server
        config = mcp_manager.get_server_config("mempalace")
        if not config:
            return {
                "facts": [],
                "status": "offline",
                "message": "Server mempalace non configurato",
            }

        # Get session using the new hybrid context manager
        async with mcp_manager.session_context("mempalace") as session:
            # DYNAMIC TOOL DISCOVERY
            tools_result = await session.list_tools()
            available_tools = [t.name for t in tools_result.tools]

            tool_to_call = None
            args = {}

            if query:
                if "mempalace_search" in available_tools:
                    tool_to_call = "mempalace_search"
                    args = {"query": query, "limit": 20}

            if not tool_to_call:
                if "mempalace_diary_read" in available_tools:
                    tool_to_call = "mempalace_diary_read"
                    args = {"agent_name": "AION", "last_n": 50}
                elif "mempalace_status" in available_tools:
                    tool_to_call = "mempalace_status"

            if not tool_to_call:
                return {
                    "facts": [],
                    "status": "partial",
                    "message": "Reading tools not found",
                }

            res = await session.call_tool(tool_to_call, arguments=args)

            facts_list = []
            if hasattr(res, "content"):
                facts_list = [c.text for c in res.content if hasattr(c, "text")]
            else:
                facts_list = [str(res)]

            return {"facts": facts_list, "status": "online", "type": "project"}

    except Exception as e:
        logger.error(f"Error calling Mempalace: {e}")
        return {"facts": [], "status": "error", "message": str(e)}


@router.post("/mcp/scan")
async def scan_mcp(req: ScanRequest):
    """Performs a security check (Antivirus) on an MCP directory or file and saves result."""
    path = req.path
    if os.path.isdir(path):
        raw_violations = await AIONAntivirus.scan_directory(path)
    else:
        _, list_v = await AIONAntivirus.scan_file(path)
        raw_violations = {path: list_v} if list_v else {}

    # Format violations with is_trusted=False for initial scan
    violations = {
        p: {"list": v_list, "is_trusted": False} for p, v_list in raw_violations.items()
    }

    is_safe = (
        all(
            not any(
                violation["severity"] in ["high", "critical"]
                for violation in v.get("list", [])
            )
            for v in violations.values()
        )
        if violations
        else True
    )

    # Persist scan result to DB if requested
    scan_id = f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if req.persist:
        async with get_async_session_maker()() as session:
            new_scan = SecurityScan(
                id=scan_id,
                target_path=path,
                is_safe=is_safe,
                results_json=json.dumps(violations),
            )
            session.add(new_scan)
            await session.commit()

    return {"id": scan_id, "is_safe": is_safe, "violations": violations}


@router.post("/mcp/install")
async def install_mcp(req: MCPInstallRequest):
    """Installs a modular MCP with venv isolation."""
    try:
        success = mcp_manager.install_stdio_server(
            req.name, req.script_path, dependencies=req.dependencies
        )
        if success and req.is_sandboxed:
            mcp_manager.update_server_config(req.name, {"security": {"sandbox": True}})

        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def build_remote_bridge_registry_config(
    url: str,
    name: str,
    description: str = "",
    auth_type: str = "oauth2",
) -> dict:
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_").upper()

    args = [
        "node_modules/mcp-remote/dist/proxy.js",
        url,
        # --transport e --transport-type sono gestiti automaticamente da mcp-remote
    ]
    env = {}

    if auth_type == "oauth2":
        env_var = f"AION_USER_{slug}__OAUTH_TOKEN"
        args.extend(["--header", "Authorization: Bearer ${" + env_var + "}"])
        env[env_var] = "${" + env_var + "}"
    elif auth_type == "api-key":
        env_var = f"AION_USER_{slug}__API_KEY"
        args.extend(["--header", "Authorization: Bearer ${" + env_var + "}"])
        env[env_var] = "${" + env_var + "}"
    elif auth_type == "basic":
        env_var = f"AION_USER_{slug}__BASIC_AUTH"
        args.extend(["--header", "Authorization: Basic ${" + env_var + "}"])
        env[env_var] = "${" + env_var + "}"
    # Se auth_type è "none": nessun header di autorizzazione, nessuna variabile d'ambiente OAuth.

    return {
        "type": "remote-bridge",
        "command": "node",
        "args": args,
        "env": env,
        "remote_url": url,
        "aion_market_install": "remote",
        "description": description,
    }


async def _install_market_record(target: Dict[str, Any], *, item_id: str = "") -> str:
    """Installa un record marketplace (da ricerca o URL GitHub manuale). Ritorna lo slug."""
    from ..runtime.mcp_installer import mcp_installer, market_safe_dir_name

    ok, err_msg = await mcp_installer.install_from_market(target)
    if not ok:
        logger.error(
            "market install failed id=%s name=%r install_type=%r: %s",
            item_id,
            target.get("name"),
            target.get("install_type"),
            err_msg,
        )
        code = 400 if target.get("install_type") == "stdio" else 500
        raise HTTPException(status_code=code, detail=err_msg or "Installazione fallita")

    name = market_safe_dir_name(target)
    catalog = load_mcp_connector_catalog()
    linked_cid = infer_connector_id_for_registry_name(name, catalog)

    sid = item_id or str(target.get("id") or "")
    config: Dict[str, Any] = {
        "description": target.get("description"),
        "source_id": sid,
    }
    if linked_cid:
        config["aion_connector_id"] = linked_cid

    if target.get("install_type") == "binary":
        script_path = os.path.join("bin", name)
        if not mcp_manager.install_stdio_server(name, script_path):
            raise HTTPException(
                status_code=500,
                detail=f"Binario non trovato dopo download: {script_path}",
            )
        mcp_manager.update_server_config(
            name,
            {
                **config,
                "aion_market_install": "binary",
                "aion_market_binary_path": f"bin/{name}".replace("\\", "/"),
            },
        )
    elif target.get("install_type") == "git":
        dest_dir = os.path.join("mcp_servers", name)
        clone_rel = f"mcp_servers/{name}".replace("\\", "/")
        config["aion_market_install"] = "git"
        config["aion_market_clone_path"] = clone_rel
        from ..mcp_registry_normalize import detect_stdio_entrypoint

        try:
            cmd, args = detect_stdio_entrypoint(name)
            config["command"] = cmd
            config["args"] = args
        except FileNotFoundError:
            logger.warning(
                "git install %s: entrypoint non rilevato, normalize post-install", name
            )
        mcp_manager._registry_local[name] = config
        mcp_manager._rebuild_merged()
        mcp_manager.save_registry()
    elif target.get("install_type") == "npx":
        config["aion_market_install"] = "npx"
        config.update(
            {
                "command": "npx",
                "args": npx_invoke_args(target),
            }
        )
        mcp_manager._registry_local[name] = config
        mcp_manager._rebuild_merged()
        mcp_manager.save_registry()
    elif target.get("install_type") == "remote":
        remotes = target.get("remotes") or []
        config["remotes"] = remotes
        config["_meta"] = target.get("_meta") or {}
        sse_url = ""
        for r in remotes:
            if isinstance(r, dict) and r.get("type") in (
                "sse",
                "streamable-http",
                "streamable_http",
            ):
                sse_url = r.get("url") or ""
                break
        if not sse_url and remotes:
            sse_url = remotes[0].get("url") if isinstance(remotes[0], dict) else ""

        import asyncio
        from ..mcp_credential_discovery import probe_remote_url_sync

        auth_type = "oauth2"
        if sse_url:
            try:
                meta = target.get("_meta") or {}
                probe_res = await asyncio.to_thread(
                    probe_remote_url_sync, sse_url, meta
                )
                auth_type = probe_res.get("type") or "oauth2"
                if auth_type not in ("none", "oauth2", "api-key", "basic"):
                    auth_type = "oauth2"
            except Exception as e:
                logger.warning(
                    "Failed to probe remote URL %s: %s. Defaulting to oauth2",
                    sse_url,
                    e,
                )

        remote_config = build_remote_bridge_registry_config(
            sse_url, name, target.get("description") or "", auth_type=auth_type
        )
        config.update(remote_config)
        mcp_manager._registry_local[name] = config
        mcp_manager._rebuild_merged()
        mcp_manager.save_registry()

    from ..mcp_integration_sync import sync_mcp_server_config_from_registry

    from ..mcp_registry_normalize import normalize_and_apply_env_after_install

    await sync_mcp_server_config_from_registry(name)
    try:
        await normalize_and_apply_env_after_install(name)
    except Exception as ex:
        logger.warning("post-install normalize failed for %s: %s", name, ex)
    return name


async def _install_marketplace_item(item_id: str) -> str:
    """Installa voce marketplace e registra in registry locale. Ritorna lo slug del server."""
    target = _find_marketplace_item(item_id)
    if not target:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Voce marketplace non trovata per id={item_id!r}. "
                "Esegui di nuovo la ricerca e premi Install, oppure installa da URL GitHub."
            ),
        )
    return await _install_market_record(target, item_id=item_id)


class GitHubInstallBody(BaseModel):
    url: str = Field(..., min_length=8, description="https://github.com/owner/repo")
    display_name: Optional[str] = None


@router.post("/market/install-github")
async def install_from_github_url(body: GitHubInstallBody):
    """Clone e registra un server MCP da URL GitHub (non richiede presenza nel marketplace)."""
    from ..marketplaces.market_adapters import build_github_market_item

    target = build_github_market_item(body.url.strip(), display_name=body.display_name)
    if not target:
        raise HTTPException(
            status_code=400,
            detail="URL non valida. Usa https://github.com/owner/repo o github:owner/repo",
        )
    try:
        name = await _install_market_record(target, item_id=str(target.get("id") or ""))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "install-github failed url=%r id=%r",
            body.url,
            target.get("id"),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {
        "status": "success",
        "name": name,
        "server_slug": name,
        "url": target.get("url"),
    }


class RemoteInstallBody(BaseModel):
    url: str = Field(..., min_length=8, description="URL del server MCP remoto")
    display_name: Optional[str] = None


@router.post("/market/install-remote")
async def install_from_remote_url(body: RemoteInstallBody):
    """Installa e registra un server MCP remoto da un URL diretto (usando mcp-remote bridge)."""
    url = body.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(
            status_code=400, detail="L'URL deve iniziare con http:// o https://"
        )

    # Estrae il nome dell'host o un valore di default
    if not body.display_name:
        import urllib.parse

        try:
            parsed = urllib.parse.urlparse(url)
            name_parts = parsed.netloc.split(".")
            if len(name_parts) >= 2:
                default_name = name_parts[-2]
            else:
                default_name = parsed.netloc or "remote_mcp"
            default_name = default_name.split(":")[0]
        except Exception:
            default_name = "remote_mcp"
    else:
        default_name = body.display_name.strip()

    target = {
        "id": f"remote:{default_name.lower()}",
        "name": default_name,
        "source": "Remote URL",
        "description": f"MCP remoto connesso a {url}",
        "url": url,
        "install_type": "remote",
        "remotes": [{"type": "sse", "url": url}],
    }
    try:
        name = await _install_market_record(target, item_id=str(target.get("id") or ""))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "install-remote failed url=%r id=%r", body.url, target.get("id")
        )
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"status": "success", "name": name, "server_slug": name, "url": url}


@router.post("/market/install")
async def install_from_market(item_id: str):
    """Installs a tool from the marketplace by its ID."""
    name = await _install_marketplace_item(item_id)
    return {"status": "success", "name": name}


@router.post("/mcp/install-from-catalog")
async def install_mcp_from_catalog_endpoint(connector_id: str):
    """Installa server MCP dal catalogo curato (senza marketplace)."""
    from ..mcp_catalog_install import install_mcp_from_catalog

    result = await install_mcp_from_catalog(connector_id.strip())
    if not result.get("ok"):
        raise HTTPException(
            status_code=404, detail=result.get("error", "Install failed")
        )
    preview = result.pop("preview", None)
    if isinstance(preview, dict) and preview.get("connector"):
        preview = {**preview, "connector_id": preview.get("aion_connector_id")}
        preview.pop("connector", None)
    return {"status": "success", **result, "integration_preview": preview}


class McpInstallWizardStartBody(BaseModel):
    server_slug: Optional[str] = None
    market_item_id: Optional[str] = None
    admin_message: Optional[str] = None


class McpInstallWizardCommitBody(BaseModel):
    server_slug: str
    registry_patch: Dict[str, Any]
    policy: Dict[str, Any]


@router.post("/mcp/install-wizard/start")
async def mcp_install_wizard_start(body: McpInstallWizardStartBody):
    """Installa da marketplace (opz.) e propone policy/env per un server nel registry."""
    from ..mcp_integration_sync import build_integration_preview

    market_id = (body.market_item_id or "").strip()
    slug = (body.server_slug or "").strip()

    if market_id:
        slug = await _install_marketplace_item(market_id)
    elif not slug:
        raise HTTPException(
            status_code=400, detail="server_slug or market_item_id required"
        )

    mcp_manager.load_registry()
    if slug not in mcp_manager._registry:
        raise HTTPException(status_code=404, detail=f"Server '{slug}' not in registry")

    # Normalizza command/args se mancanti (es. progetti TS senza dist/ dopo git clone)
    from ..mcp_registry_normalize import normalize_installed_server_registry

    try:
        normalize_installed_server_registry(slug)
    except Exception:
        pass  # non bloccare il wizard per errori di normalizzazione

    advise_body = McpIntegrationAdviseBody(
        server_slug=slug,
        admin_message=body.admin_message,
    )
    advise = await admin_advise_mcp_integration(advise_body)
    preview = build_integration_preview(slug)
    if isinstance(preview, dict) and preview.get("connector"):
        preview = {k: v for k, v in preview.items() if k != "connector"}
    registry_cfg = mcp_manager._registry.get(slug) or {}
    return {
        "status": "success",
        "server_slug": slug,
        "registry_config": registry_cfg,
        "preview": preview,
        "advise": advise,
    }


@router.post("/mcp/install-wizard/commit")
async def mcp_install_wizard_commit(body: McpInstallWizardCommitBody):
    """Salva registry + policy in un'unica operazione (pipeline unificato)."""
    from ..mcp_integration_sync import apply_integration_config

    slug = body.server_slug.strip()
    mcp_manager.load_registry()
    if slug not in mcp_manager._registry:
        raise HTTPException(status_code=404, detail="Server not in registry")

    policy = body.policy or {}
    mode = policy.get("credential_mode", "none")
    if mode not in ("none", "org_shared", "per_user"):
        mode = "none"
    schema_override = bool(policy.get("schema_override", False))
    cred_schema = policy.get("credential_schema") if schema_override else None
    env_override = (
        policy.get("suggested_env")
        if isinstance(policy.get("suggested_env"), dict)
        else None
    )
    oauth_config = (
        policy.get("oauth_config")
        if isinstance(policy.get("oauth_config"), dict)
        else None
    )

    result = await apply_integration_config(
        slug,
        credential_mode=mode,
        credential_schema=cred_schema,
        env_override=env_override,
        apply_suggested_env=bool(policy.get("apply_suggested_env")),
        schema_override=schema_override,
        registry_patch=body.registry_patch,
        is_enabled_for_users=policy.get("is_enabled_for_users"),
        requires_user_credentials=policy.get("requires_user_credentials"),
        user_may_disable=policy.get("user_may_disable"),
        display_name=policy.get("display_name"),
        oauth_config=oauth_config,
        sync_db=True,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Apply failed"))

    async with get_async_session_maker()() as session:
        exists = (
            (
                await session.execute(
                    select(McpServerConfig.id).where(
                        McpServerConfig.server_slug == slug
                    )
                )
            )
            .scalars()
            .first()
        )
    if not exists:
        create_body = McpIntegrationCreate(
            server_slug=slug,
            display_name=policy.get("display_name") or slug.replace("_", " ").title(),
            is_enabled_for_users=bool(policy.get("is_enabled_for_users")),
            credential_mode=mode,
            requires_user_credentials=bool(
                policy.get("requires_user_credentials", mode == "per_user")
            ),
            credential_schema=cred_schema or [],
            user_may_disable=policy.get("user_may_disable", True),
            oauth_config=oauth_config,
        )
        await admin_create_mcp_integration(create_body)

    return {
        "status": "success",
        "server_slug": slug,
        **{k: v for k, v in result.items() if k != "ok"},
    }


@router.post("/mcp/{name}/probe")
async def probe_mcp_server(name: str):
    """Esegue list_tools sul server MCP (handshake) per validazione post-install."""
    from ..main import build_mcp_tools

    mcp_manager.load_registry()
    if name not in mcp_manager._registry:
        raise HTTPException(status_code=404, detail="MCP not in registry")
    cfg = mcp_manager.get_server_config(name) or {}
    t = (cfg.get("type") or "stdio").lower()
    if t == "remote-bridge":
        import shutil
        import os

        local_path = os.path.join(
            os.getcwd(), "node_modules", "mcp-remote", "dist", "proxy.js"
        )
        has_local = os.path.exists(local_path)
        if has_local:
            if not shutil.which("node"):
                return {
                    "ok": False,
                    "server_slug": name,
                    "error": "node command not found. Node.js is required to run remote-bridge.",
                    "tools": [],
                    "tool_count": 0,
                }
        else:
            if not shutil.which("npx"):
                return {
                    "ok": False,
                    "server_slug": name,
                    "error": "npx command not found and local mcp-remote not installed. Node.js/npm is required.",
                    "tools": [],
                    "tool_count": 0,
                }
    try:
        tools = await build_mcp_tools(
            name, cfg, session_id="mcp-probe", user_id="admin-probe"
        )
        return {
            "ok": True,
            "server_slug": name,
            "tool_count": len(tools),
            "tools": [
                {
                    "name": getattr(t, "name", ""),
                    "description": getattr(t, "description", "") or "",
                }
                for t in tools
            ],
        }
    except Exception as e:
        logger.exception("MCP probe failed for %s", name)
        return {
            "ok": False,
            "server_slug": name,
            "error": str(e),
            "tools": [],
            "tool_count": 0,
        }


@router.put("/mcp/{name}")
async def update_mcp_config(name: str, config: MCPUpdate):
    """Updates configuration for an existing MCP server."""
    if name not in mcp_manager._registry:
        raise HTTPException(status_code=404, detail="MCP not found")

    update_data = config.model_dump(exclude_unset=True)

    # Cleanup per credential_mode="none": rimuovi env e --header args per remote-bridge
    if update_data:
        async with get_async_session_maker()() as session:
            row = (
                (
                    await session.execute(
                        select(McpServerConfig).where(
                            McpServerConfig.server_slug == name
                        )
                    )
                )
                .scalars()
                .first()
            )

        if row and row.credential_mode == "none":
            cfg = mcp_manager.get_server_config(name) or {}
            is_remote = (
                cfg.get("type") == "remote-bridge"
                or cfg.get("aion_market_install") == "remote"
            )

            if is_remote:
                # 1) Rimuovi env (non serve quando credential_mode è "none")
                if "env" in update_data:
                    del update_data["env"]

                # 2) Rimuovi --header 'Authorization: Bearer...' dagli args
                args = update_data.get("args")
                if args:
                    cleaned: List[str] = []
                    skip_next = False
                    for arg in args:
                        if skip_next:
                            skip_next = False
                            continue
                        if arg == "--header":
                            skip_next = True
                            continue
                        cleaned.append(arg)
                    if cleaned != args:
                        update_data["args"] = cleaned

    try:
        updated = mcp_manager.update_server_config(name, update_data)
    except KeyError:
        raise HTTPException(status_code=404, detail="MCP not found")
    from ..mcp_integration_sync import sync_mcp_server_config_from_registry

    await sync_mcp_server_config_from_registry(name)
    return {"status": "success", "config": updated}


@router.get("/stats")
async def get_stats():
    """Aggregates system-wide statistics for the dashboard."""
    profiles = profile_manager.list_profiles()

    skill_registry.reload()
    skills_count = len(skill_registry.get_all_names())

    mcp_count = len(mcp_manager._registry)

    # Calculate scheduled jobs and api keys
    jobs_total = 0
    jobs_enabled = 0
    api_keys_total = 0
    api_keys_by_scope = {}
    model_usage = {}
    projects_total = 0

    from ..data.models import (
        Conversation,
        LlmProvider,
        ApiKey,
        ScheduledJob,
        SqlQueryProject,
    )
    from sqlalchemy import select

    try:
        async with get_async_session_maker()() as session:
            # 1) Get all providers to resolve slugs to display names
            providers_query = select(LlmProvider)
            providers = (await session.execute(providers_query)).scalars().all()
            provider_names = {p.slug: p.display_name for p in providers}
            default_provider = next((p for p in providers if p.is_default), None)
            default_name = (
                default_provider.display_name
                if default_provider
                else (default_provider.slug if default_provider else "Default Model")
            )

            # 2) Get all conversations metadata
            conv_query = select(Conversation.metadata_json)
            convs = (await session.execute(conv_query)).scalars().all()

            for meta_str in convs:
                try:
                    meta = json.loads(meta_str or "{}")
                    prov_slug = meta.get("llm_provider_name")
                    if prov_slug and prov_slug in provider_names:
                        name = provider_names[prov_slug]
                    elif default_provider:
                        name = default_name
                    else:
                        name = "Default Model"
                    model_usage[name] = model_usage.get(name, 0) + 1
                except Exception:
                    name = default_name if default_provider else "Default Model"
                    model_usage[name] = model_usage.get(name, 0) + 1

            # 3) Get scheduled jobs
            jobs_rows = (await session.execute(select(ScheduledJob))).scalars().all()
            jobs_total = len(jobs_rows)
            jobs_enabled = sum(1 for j in jobs_rows if j.enabled)

            # 4) Get API keys and group by scopes
            keys_rows = (await session.execute(select(ApiKey))).scalars().all()
            api_keys_total = len(keys_rows)
            for k in keys_rows:
                scopes = json.loads(k.scopes_json or "[]")
                if not scopes:
                    api_keys_by_scope["no_scopes"] = (
                        api_keys_by_scope.get("no_scopes", 0) + 1
                    )
                for s in scopes:
                    api_keys_by_scope[s] = api_keys_by_scope.get(s, 0) + 1

            # 5) Get SQL query projects count
            projects_rows = (
                (await session.execute(select(SqlQueryProject))).scalars().all()
            )
            projects_total = len(projects_rows)
    except Exception as e:
        logger.exception("Failed to query database stats: %s", e)

    return {
        "active_profiles": len(profiles),
        "total_skills": skills_count,
        "installed_mcp": mcp_count,
        "security_score": "100%",  # Placeholder for future dynamic score
        "recent_scans": 5,  # Placeholder
        "model_usage": model_usage,
        "total_projects": projects_total,
        "cron_jobs": {
            "total": jobs_total,
            "enabled": jobs_enabled,
        },
        "api_keys": {
            "total": api_keys_total,
            "by_scope": api_keys_by_scope,
        },
    }


@router.delete("/mcp/{name}")
async def delete_mcp(name: str):
    """Rimuove il server dal registry locale e, se installato dal marketplace, elimina clone/binario."""
    if name in mcp_manager._registry_base:
        raise HTTPException(
            status_code=400, detail="Impossibile eliminare i moduli MCP di sistema."
        )

    from ..agent_profile import profile_manager

    # Ricarica e verifica utilizzo nei profili
    profile_manager.load_all()
    referencing_profiles = []
    for p in profile_manager._profiles.values():
        if name in p.mcp_servers:
            referencing_profiles.append(p.name)

    if referencing_profiles:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "mcp_in_use",
                "message": f"Impossibile eliminare il server MCP. È in uso nei seguenti profili: {', '.join(referencing_profiles)}",
                "profiles": referencing_profiles,
            },
        )

    cfg = copy.deepcopy(mcp_manager._registry.get(name) or {})
    if not mcp_manager.delete_server(name):
        raise HTTPException(status_code=404, detail="MCP not found")
    _remove_market_mcp_artifacts(name, cfg)
    # Pulisci anche la riga McpServerConfig (policy) se presente
    async with get_async_session_maker()() as session:
        await session.execute(
            delete(McpServerConfig).where(McpServerConfig.server_slug == name)
        )
        await session.commit()
    return {"status": "success"}


@router.get("/plugins")
async def admin_list_plugins():
    root = _project_root() / "data" / "plugins"
    if not root.is_dir():
        return {"plugins": []}
    return {
        "plugins": [
            p.stem for p in sorted(root.glob("*.py")) if not p.name.startswith("_")
        ]
    }


@router.post("/plugins/reload")
async def admin_reload_plugins():
    from src.runtime.plugin_loader import load_plugins

    return {"loaded": load_plugins()}


@router.get("/subagents")
async def list_subagents():
    """YAML definitions under config/subagents/."""
    root = _project_root() / "config" / "subagents"
    if not root.is_dir():
        return {"subagents": []}
    out = []
    for p in sorted(root.glob("*.yaml")):
        try:
            body = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            body = {}
        out.append(
            {"name": p.stem, "file": str(p.relative_to(_project_root())), "meta": body}
        )
    return {"subagents": out}


# --- V2 ADDITIONS ---


@router.get("/system/health")
async def get_system_health():
    """Detailed health info for V2 components."""
    from ..storage.factory import get_storage_backend

    r_status = redis_status()

    # DB Status
    db_url = os.getenv("AION_DB_URL", "sqlite+aiosqlite:///data/aion.db")
    db_size = -1
    if "sqlite" in db_url:
        db_path = db_url.split("///")[-1]
        if os.path.exists(db_path):
            db_size = os.path.getsize(db_path)

    storage = get_storage_backend()
    storage_type = "s3" if hasattr(storage, "bucket") else "local"

    return {
        "redis": r_status,
        "database": {
            "url": db_url.split("@")[-1] if "@" in db_url else db_url,
            "size_bytes": db_size,
            "unified": os.getenv("AION_UNIFIED_DB", "1") == "1",
        },
        "storage": {
            "backend": storage_type,
            "local_root": os.getenv("AION_STORAGE_LOCAL_ROOT", "data"),
        },
    }


@router.get("/diagnostics/json-recovery")
async def json_recovery_stats():
    """Statistiche recovery JSON tool call arguments (patch Haystack streaming)."""
    from ..runtime.json_recovery import get_recovery_stats

    return get_recovery_stats()


class ApiKeyCreate(BaseModel):
    name: str
    tenant_id: str = "default"
    scopes: List[str] = ["chat:scoped"]
    expires_in_days: Optional[int] = None


class UserCreate(BaseModel):
    identifier: str
    password: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    tenant_id: str = "default"
    roles: List[str] = []
    must_change_password: bool = False


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    roles: Optional[List[str]] = None
    must_change_password: Optional[bool] = None


class UserProfilesUpdate(BaseModel):
    allowed_profiles: List[str]


@router.get("/users")
async def list_users():
    """List all users in the unified database."""
    from ..data.models import User
    from ..data.user_password import get_roles

    async with get_async_session_maker()() as session:
        q = select(User).order_by(User.created_at.desc())
        rows = (await session.execute(q)).scalars().all()
        return {
            "users": [
                {
                    "id": r.id,
                    "tenant_id": r.tenant_id,
                    "identifier": r.identifier,
                    "display_name": r.display_name,
                    "email": r.email,
                    "roles": get_roles(r),
                    "must_change_password": bool(
                        getattr(r, "must_change_password", False)
                    ),
                    "created_at": r.created_at,
                    "last_active_at": r.last_active_at,
                }
                for r in rows
            ]
        }


@router.post("/users")
async def create_user(body: UserCreate):
    """Create a new user."""
    try:
        uid = await create_password_user(
            tenant_id=body.tenant_id,
            identifier=body.identifier,
            password=body.password,
            display_name=body.display_name,
            email=body.email,
            roles=body.roles or [],
            must_change_password=body.must_change_password,
        )
    except UserAlreadyExistsError:
        raise HTTPException(status_code=400, detail="User already exists")
    return {"status": "success", "id": uid}


@router.put("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate):
    """Update an existing user."""
    from ..data.models import User
    from ..data.user_password import hash_password, set_roles

    async with get_async_session_maker()() as session:
        u = await session.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        if body.display_name is not None:
            u.display_name = body.display_name
        if body.email is not None:
            u.email = body.email
        if body.password:
            u.password_hash = hash_password(body.password)
            # Reset del flag se l'admin assegna una nuova password manualmente.
            u.must_change_password = False
        if body.roles is not None:
            set_roles(u, body.roles)
        if body.must_change_password is not None:
            u.must_change_password = bool(body.must_change_password)

        await session.commit()

    return {"status": "success"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str):
    """Delete a user."""
    from ..data.models import User, UserProfileAccess

    async with get_async_session_maker()() as session:
        await session.execute(delete(User).where(User.id == user_id))
        await session.execute(
            delete(UserProfileAccess).where(UserProfileAccess.user_id == user_id)
        )
        await session.commit()
    return {"status": "success"}


@router.get("/users/{user_id}/profiles")
async def get_user_profiles(user_id: str):
    """Get the list of profiles allowed for a user."""
    from ..data.models import UserProfileAccess

    async with get_async_session_maker()() as session:
        q = select(UserProfileAccess.profile_slug).where(
            UserProfileAccess.user_id == user_id
        )
        rows = (await session.execute(q)).scalars().all()
        return {"allowed_profiles": list(rows)}


@router.post("/users/{user_id}/profiles")
async def update_user_profiles(user_id: str, body: UserProfilesUpdate):
    """Update the list of profiles allowed for a user."""
    from ..data.models import User, UserProfileAccess

    async with get_async_session_maker()() as session:
        # Check user exists
        u = await session.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        # Clear existing access
        await session.execute(
            delete(UserProfileAccess).where(UserProfileAccess.user_id == user_id)
        )

        # Add new access rules
        tenant_id = u.tenant_id or "default"
        for slug in body.allowed_profiles:
            new_access = UserProfileAccess(
                tenant_id=tenant_id,
                user_id=user_id,
                profile_slug=slug,
            )
            session.add(new_access)

        await session.commit()

    return {"status": "success"}


@router.get("/api-keys")
async def list_api_keys():
    """List all API keys (admin only)."""
    async with get_async_session_maker()() as session:
        q = select(ApiKey).order_by(ApiKey.created_at.desc())
        rows = (await session.execute(q)).scalars().all()
        return {
            "keys": [
                {
                    "id": r.id,
                    "tenant_id": r.tenant_id,
                    "name": r.name,
                    "prefix": r.prefix,
                    "scopes": json.loads(r.scopes_json or "[]"),
                    "created_at": r.created_at,
                    "expires_at": r.expires_at,
                    "last_used_at": r.last_used_at,
                    "revoked_at": r.revoked_at,
                }
                for r in rows
            ]
        }


@router.post("/api-keys")
async def create_api_key(body: ApiKeyCreate):
    """Generate a new API key."""
    from ..data.ids import new_uuid7_str
    from ..api.auth.api_key import generate_api_key_pair, hash_api_key
    from datetime import timedelta

    raw_key, prefix, secret = generate_api_key_pair()
    hashed = hash_api_key(raw_key)

    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.now() + timedelta(days=body.expires_in_days)

    async with get_async_session_maker()() as session:
        new_key = ApiKey(
            id=new_uuid7_str(),
            tenant_id=body.tenant_id,
            name=body.name,
            prefix=prefix,
            hash=hashed,
            scopes_json=json.dumps(body.scopes),
            expires_at=expires_at,
        )
        session.add(new_key)
        await session.commit()

    return {
        "id": new_key.id,
        "name": new_key.name,
        "key": raw_key,  # RETURNED ONLY ONCE
        "prefix": prefix,
        "scopes": body.scopes,
        "expires_at": expires_at,
    }


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str):
    async with get_async_session_maker()() as session:
        await session.execute(delete(ApiKey).where(ApiKey.id == key_id))
        await session.commit()
    return {"status": "revoked"}


@router.get("/conversations/global")
async def list_conversations_global(limit: int = 50):
    """List all conversations across all users/tenants."""
    async with get_async_session_maker()() as session:
        q = select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
        rows = (await session.execute(q)).scalars().all()
        return {
            "conversations": [
                {
                    "id": r.id,
                    "tenant_id": r.tenant_id,
                    "user_id": r.user_id,
                    "profile_slug": r.profile_slug,
                    "title": r.title,
                    "message_count": r.message_count,
                    "updated_at": r.updated_at,
                    "metadata": json.loads(r.metadata_json or "{}"),
                }
                for r in rows
            ]
        }


@router.get("/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: str, include_internal: bool = False):
    """Retrieve full message history for a conversation including steps and artifacts."""
    async with get_async_session_maker()() as session:
        # Fetch Messages
        q_msg = (
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.seq.asc())
        )
        msgs = (await session.execute(q_msg)).scalars().all()

        # Fetch Steps
        q_steps = (
            select(Step)
            .where(Step.conversation_id == conv_id)
            .order_by(Step.created_at.asc())
        )
        steps = (await session.execute(q_steps)).scalars().all()

        # Fetch Attachments
        q_att = (
            select(Attachment)
            .where(Attachment.conversation_id == conv_id)
            .order_by(Attachment.created_at.asc())
        )
        atts = (await session.execute(q_att)).scalars().all()

        # Group steps and attachments by message_id
        steps_by_msg = {}
        for s in steps:
            mid = s.message_id or "orphan"
            steps_by_msg.setdefault(mid, []).append(
                {
                    "id": s.id,
                    "name": s.name,
                    "type": s.type,
                    "input": s.input,
                    "output": s.output,
                    "is_error": bool(s.is_error),
                    "created_at": s.created_at,
                }
            )

        atts_by_msg = {}
        for a in atts:
            mid = a.message_id or "orphan"
            atts_by_msg.setdefault(mid, []).append(
                {
                    "id": a.id,
                    "storage_key": a.storage_key,
                    "original_name": a.original_name,
                    "mime": a.mime,
                    "size_bytes": a.size_bytes,
                    "kind": a.kind,
                    "created_at": a.created_at,
                }
            )

        data = []
        orphan_steps = list(steps_by_msg.get("orphan", []))
        orphan_atts = list(atts_by_msg.get("orphan", []))

        for r in msgs:
            nr = normalize_message_role(r.role)

            # Collect steps and attachments for this message
            current_steps = steps_by_msg.get(r.id, [])
            current_atts = atts_by_msg.get(r.id, [])

            if not include_internal and (
                (not is_ui_visible_role(nr))
                or looks_like_internal_content(r.content)
                or looks_like_raw_plan_content(r.content)
                or is_empty_technical_message(nr, r.content)
            ):
                continue

            final_steps = current_steps
            final_atts = current_atts
            if nr == "assistant":
                # Legacy fallback only: older records may have no message_id.
                final_steps = orphan_steps + final_steps
                final_atts = orphan_atts + final_atts
                orphan_steps = []
                orphan_atts = []

            data.append(
                {
                    "id": r.id,
                    "role": nr,
                    "content": r.content,
                    "reasoning": r.reasoning,
                    "tool_name": r.tool_name,
                    "tool_call_id": r.tool_call_id,
                    "created_at": r.created_at,
                    "seq": r.seq,
                    "steps": final_steps,
                    "artifacts": final_atts,
                }
            )
        return {"messages": data}


@router.get("/conversations/{conv_id}/render-audit")
async def get_conversation_render_audit(conv_id: str):
    """
    Debug endpoint: shows why records are rendered or filtered in resume UI.
    Useful to diagnose role leakage and legacy step issues.
    """
    async with get_async_session_maker()() as session:
        msg_rows = (
            (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conv_id)
                    .order_by(Message.seq.asc())
                )
            )
            .scalars()
            .all()
        )
        step_rows = (
            (
                await session.execute(
                    select(Step)
                    .where(Step.conversation_id == conv_id)
                    .order_by(Step.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    msg_summary: Dict[str, int] = {}
    hidden_internal = 0
    hidden_content_marker = 0
    internal_trigger_messages = 0
    raw_plan_messages = 0
    empty_assistant_messages = 0
    empty_tool_messages = 0
    message_samples: List[Dict[str, Any]] = []
    for m in msg_rows:
        nr = normalize_message_role(m.role)
        msg_summary[nr] = msg_summary.get(nr, 0) + 1
        hidden_role = not is_ui_visible_role(nr)
        hidden_marker = looks_like_internal_content(m.content)
        is_raw_plan = looks_like_raw_plan_content(m.content)
        is_empty_tech = is_empty_technical_message(nr, m.content)
        reason_codes = _message_render_reason_codes(m.role, m.content)
        if hidden_role:
            hidden_internal += 1
        if hidden_marker:
            hidden_content_marker += 1
        if nr in {"internal", "system"}:
            internal_trigger_messages += 1
        if is_raw_plan:
            raw_plan_messages += 1
        if nr == "assistant" and not (m.content or "").strip():
            empty_assistant_messages += 1
        if nr == "tool" and not (m.content or "").strip():
            empty_tool_messages += 1
        if len(message_samples) < 20:
            message_samples.append(
                {
                    "id": m.id,
                    "seq": m.seq,
                    "role_raw": m.role,
                    "role_normalized": nr,
                    "ui_visible": not (
                        hidden_role or hidden_marker or is_raw_plan or is_empty_tech
                    ),
                    "hidden_by_role": hidden_role,
                    "hidden_by_content_marker": hidden_marker,
                    "hidden_by_raw_plan": is_raw_plan,
                    "hidden_by_empty_technical": is_empty_tech,
                    "reason_codes": reason_codes,
                    "content_preview": (m.content or "")[:160],
                }
            )

    step_type_summary: Dict[str, int] = {}
    legacy_step_types = {"message", "user_message", "assistant_message"}
    legacy_steps = 0
    step_samples: List[Dict[str, Any]] = []
    for s in step_rows:
        t = (s.type or "").strip()
        step_type_summary[t] = step_type_summary.get(t, 0) + 1
        if t in legacy_step_types:
            legacy_steps += 1
        if len(step_samples) < 20:
            step_samples.append(
                {
                    "id": s.id,
                    "type": t,
                    "name": s.name,
                    "parent_id": s.parent_id,
                    "output_preview": (s.output or "")[:160],
                }
            )

    return {
        "conversation_id": conv_id,
        "messages_total": len(msg_rows),
        "steps_total": len(step_rows),
        "message_roles": msg_summary,
        "message_hidden_by_internal_role": hidden_internal,
        "message_hidden_by_internal_marker": hidden_content_marker,
        "internal_trigger_messages": internal_trigger_messages,
        "raw_plan_messages": raw_plan_messages,
        "empty_assistant_messages": empty_assistant_messages,
        "empty_tool_messages": empty_tool_messages,
        "step_types": step_type_summary,
        "legacy_message_like_steps": legacy_steps,
        "message_samples": message_samples,
        "step_samples": step_samples,
    }


@router.get("/profiling/bottlenecks")
async def get_profiling_bottlenecks():
    """Restituisce le analisi e i colli di bottiglia basati sui JSONL del profiler."""
    from ..profiling.bottleneck import detector

    return detector.detect()


@router.get("/eval/runs")
async def list_eval_runs(limit: int = 20):
    """List recent evaluation runs."""
    from ..data.models import EvalRun

    async with get_async_session_maker()() as session:
        q = select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit)
        rows = (await session.execute(q)).scalars().all()
        return {
            "runs": [
                {
                    "id": r.id,
                    "dataset_name": r.dataset_name,
                    "profile_name": r.profile_name,
                    "overall_score": r.overall_score,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
        }


@router.get("/eval/runs/{run_id}/results")
async def get_eval_results(run_id: str):
    """Get detailed results for a specific evaluation run."""
    from ..data.models import EvalResult

    async with get_async_session_maker()() as session:
        q = select(EvalResult).where(EvalResult.run_id == run_id)
        rows = (await session.execute(q)).scalars().all()
        return {
            "results": [
                {
                    "case_id": r.case_id,
                    "input_text": r.input_text,
                    "score": r.score,
                    "reasoning": r.reasoning,
                    "latency_sec": r.latency_sec,
                }
                for r in rows
            ]
        }
