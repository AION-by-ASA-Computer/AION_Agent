# src/api/admin.py
import logging
import re
import os
import yaml
import frontmatter
from typing import List, Dict, Any, Optional
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
import io
import zipfile
import shutil
import copy
from pydantic import BaseModel, Field
from ..agent_profile import profile_manager
from ..skill_registry import skill_registry
from ..mcp_manager import mcp_manager
from ..security.checker import AIONAntivirus
from ..marketplaces.market_adapters import hub_aggregator, npx_invoke_args
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import urllib.parse
from sse_starlette.sse import EventSourceResponse
from ..mcp_remote_install import build_remote_bridge_registry_config
from ..runtime.mcp_health import (
    classify_mcp_error,
    clear_mcp_load_errors,
    get_last_mcp_load_errors,
    merge_probe_env,
)


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
from .auth_login import ChatAuthIdentity, require_admin_role
from .settings_api import router as settings_router
from .ltm_admin import router as ltm_admin_router
from .admin_profile_memory import router as admin_profile_memory_router
from .cron_admin import router as cron_admin_router
from .admin_query_memory import router as admin_query_memory_router
from .llm_providers import router as llm_providers_router
from .metrics_api import router as metrics_router
from .version_check import router as version_check_router
from .admin_diagnostics import router as diagnostics_router
from .admin_sso import router as admin_sso_router
from ..runtime.redis_client import redis_status
from ..data.engine import get_async_session_maker
from ..mcp_connector_catalog import (
    infer_connector_id_for_registry_name,
    load_mcp_connector_catalog,
)
from ..data.user_password import (
    UserAlreadyExistsError,
    create_invited_user,
)
from ..data import api_keys as api_keys_db
from ..data.models import (
    Conversation,
    Message,
    SecurityScan,
    McpServerConfig,
)
from ..data.ids import new_uuid7_str
from sqlalchemy import select, delete, func

logger = logging.getLogger("aion.api.admin")

_SECRET_KEY_PATTERNS = (
    "KEY",
    "TOKEN",
    "PASSWORD",
    "SECRET",
    "AUTH",
    "PASS",
    "CREDENTIAL",
    "PRIVATE",
    "BEARER",
)


def _is_secret_key(key: str) -> bool:
    if not isinstance(key, str):
        return False
    k = key.upper()
    return any(p in k for p in _SECRET_KEY_PATTERNS)


def _is_literal_secret(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    v = val.strip()
    return bool(v) and not v.startswith("${")


def _synthetic_npx_market_item(item_id: str) -> Optional[Dict[str, Any]]:
    """Build install payload from ``npx:package`` without re-searching marketplaces."""
    s = (item_id or "").strip()
    if not s.lower().startswith("npx:"):
        return None
    pkg = s.split(":", 1)[-1].strip()
    if not pkg:
        return None
    pkg.split("/")[-1].replace("@", "").replace(".", "_") or "mcp_npx"
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
    slug: Optional[str] = None
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
    remote_url: Optional[str] = None


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


router.include_router(settings_router)
router.include_router(ltm_admin_router)
router.include_router(admin_profile_memory_router)
router.include_router(cron_admin_router)
router.include_router(admin_query_memory_router)
router.include_router(llm_providers_router)
router.include_router(metrics_router)
router.include_router(version_check_router)
router.include_router(diagnostics_router)
router.include_router(admin_sso_router)


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


_PRIVATE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".db-journal")


def _is_private_data_path(path: Path) -> bool:
    """True for files that may hold users' chats (data dir, DB files, env secrets)."""
    from ..session_workspace import data_root

    resolved = path.resolve()
    name = resolved.name.lower()
    if name.startswith(".env") or name.endswith(_PRIVATE_SUFFIXES):
        return True
    return _is_under_dir(resolved, data_root()) or _is_under_dir(
        resolved, _project_root() / "data"
    )


_SECRET_NAME_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def _investigable_path(raw: str) -> Optional[Path]:
    """Percorso che /security/investigate puo' leggere, oppure None.

    Solo file del progetto (i percorsi relativi delle scansioni partono dalla
    root), mai dati utente, segreti o metadati git: il contenuto finisce nel
    prompt dell'LLM e nel report salvato. ``resolve()`` segue i symlink, quindi
    un link verso l'esterno del progetto viene rifiutato.
    """
    root = _project_root().resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not _is_under_dir(resolved, root) or _is_private_data_path(resolved):
        return None
    rel_parts = resolved.relative_to(root).parts
    name = resolved.name.lower()
    if ".git" in rel_parts or ".local." in name or name.endswith(_SECRET_NAME_SUFFIXES):
        return None
    return resolved


@router.get("/security/investigate")
async def investigate_code(path: str, profile: str = "Security Officer"):
    """
    Triggers an LLM-based investigation of a specific file using a selectable profile.
    Returns a stream of tokens and reasoning.
    """

    # Prima il controllo, poi l'esistenza: fuori dal progetto non si sonda nulla.
    target = _investigable_path(path)
    if target is None:
        raise HTTPException(status_code=403, detail="Path not allowed")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        with open(target, "r", encoding="utf-8") as f:
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


class WizardPromptRequest(BaseModel):
    prompt: str = Field(
        ...,
        min_length=1,
        description="Prompt in linguaggio naturale per la generazione",
    )
    messages: Optional[List[Dict[str, str]]] = Field(
        None, description="Storico messaggi per affinamento multi-turn"
    )


@router.post("/profiles/wizard-generate")
async def wizard_generate_profile(req: WizardPromptRequest):
    from ..runtime.wizard_generator import generate_profile_wizard

    try:
        return await generate_profile_wizard(req.prompt, history=req.messages)
    except Exception as exc:
        logger.error("Profile wizard generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Generazione profilo fallita: {exc}"
        )


@router.post("/profiles/wizard-suggest")
async def wizard_suggest_profile(req: WizardPromptRequest):
    from ..runtime.wizard_generator import suggest_profile_enhancements

    try:
        return await suggest_profile_enhancements(req.prompt, history=req.messages)
    except Exception as exc:
        logger.error("Profile wizard suggestion failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Generazione suggerimenti fallita: {exc}"
        )


class WizardRefineProfileRequest(BaseModel):
    prompt: str = Field(
        ..., min_length=1, description="Prompt per la modifica/affinamento in-place"
    )
    current_profile: Dict[str, Any] = Field(
        ..., description="Stato attuale del profilo da modificare"
    )


@router.post("/profiles/wizard-refine")
async def wizard_refine_profile(req: WizardRefineProfileRequest):
    from ..runtime.wizard_generator import refine_profile_wizard

    try:
        return await refine_profile_wizard(req.prompt, req.current_profile)
    except Exception as exc:
        logger.error("Profile wizard refine failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Modifica profilo fallita: {exc}")


@router.post("/skills/wizard-generate")
async def wizard_generate_skill(req: WizardPromptRequest):
    from ..runtime.wizard_generator import generate_skill_wizard

    try:
        return await generate_skill_wizard(req.prompt, history=req.messages)
    except Exception as exc:
        logger.error("Skill wizard generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generazione skill fallita: {exc}")


class WizardRefineSkillRequest(BaseModel):
    prompt: str = Field(
        ...,
        min_length=1,
        description="Prompt per la modifica/affinamento in-place della skill",
    )
    current_skill: Dict[str, Any] = Field(
        ..., description="Stato attuale della skill da modificare"
    )


@router.post("/skills/wizard-refine")
async def wizard_refine_skill(req: WizardRefineSkillRequest):
    from ..runtime.wizard_generator import refine_skill_wizard

    try:
        return await refine_skill_wizard(req.prompt, req.current_skill)
    except Exception as exc:
        logger.error("Skill wizard refine failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Modifica skill fallita: {exc}")


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


class SkillRename(BaseModel):
    new_name: str


_SKILL_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@router.post("/skills/{name}/rename")
async def rename_skill(name: str, body: SkillRename):
    """Rename a skill on disk and rewrite every profile that references it."""
    from ..runtime.profile_sync_state import record_profile_after_admin_save

    new = body.new_name.strip().lower().replace(" ", "_")
    if not _SKILL_SLUG_RE.match(new):
        raise HTTPException(
            status_code=400,
            detail="Invalid name: use lowercase letters, digits, '_' or '-'.",
        )
    # Belt-and-suspenders: strip any path component so `new` can never be
    # anything but a bare filename, regardless of what the regex above allows.
    new = os.path.basename(new)
    skill_registry.reload()
    path = skill_registry.get_skill_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="Skill not found")
    if new == name:
        return {"status": "unchanged", "name": name, "profiles": []}
    if skill_registry.skill_exists(new):
        raise HTTPException(
            status_code=409, detail=f"A skill named '{new}' already exists"
        )
    fallback = skill_registry.curated_fallback_dir.resolve()
    from_fallback = (
        fallback == path.resolve().parent or fallback in path.resolve().parents
    )

    roots = {
        skill_registry.curated_dir.resolve(),
        skill_registry.generated_dir.resolve(),
    }
    is_package = (
        path.name.lower() in ("skill.md", "index.md")
        and path.parent.resolve() not in roots
    )
    if from_fallback:
        # Shipped skills are read-only: copy into the writable dir; the old name gets hidden below.
        new_file = (skill_registry.curated_dir / f"{new}.md").resolve()
        if new_file.parent != skill_registry.curated_dir.resolve():
            raise HTTPException(status_code=400, detail="Invalid name")
        if new_file.exists():
            raise HTTPException(
                status_code=409, detail=f"'{new_file.name}' already exists on disk"
            )
        new_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, new_file)
    elif is_package:
        dest_dir = path.parent.with_name(new).resolve()
        if dest_dir.parent != path.parent.resolve().parent:
            raise HTTPException(status_code=400, detail="Invalid name")
        if dest_dir.exists():
            raise HTTPException(
                status_code=409, detail=f"'{dest_dir.name}' already exists on disk"
            )
        path.parent.rename(dest_dir)
        new_file = dest_dir / path.name
    else:
        new_file = path.with_name(f"{new}.md").resolve()
        if new_file.parent != path.resolve().parent:
            raise HTTPException(status_code=400, detail="Invalid name")
        if new_file.exists():
            raise HTTPException(
                status_code=409, detail=f"'{new_file.name}' already exists on disk"
            )
        path.rename(new_file)

    skill_registry.unhide(new)
    # The frontmatter `name` wins over the file stem when the registry loads skills.
    post = frontmatter.loads(new_file.read_text(encoding="utf-8"))
    post.metadata["name"] = new
    new_file.write_text(frontmatter.dumps(post), encoding="utf-8")

    skill_registry.reload()
    if skill_registry.skill_exists(name):
        # A shipped copy (config_std) still defines the old name: hide it so it's a rename, not a copy.
        skill_registry.hide(name)

    updated: List[str] = []
    profile_manager.load_all()
    for p in list(profile_manager._profiles.values()):
        in_skills = name in (p.skills or [])
        in_critical = name in (p.critical_skills or [])
        if not (in_skills or in_critical):
            continue
        src_path = profile_manager.profile_yaml_path(p.slug)
        data = yaml.safe_load(src_path.read_text(encoding="utf-8")) or {}
        for key in ("skills", "critical_skills"):
            items = data.get(key)
            if isinstance(items, list):
                data[key] = [new if x == name else x for x in items]
        out = profile_manager.profile_yaml_path(p.slug, for_write=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, allow_unicode=True, sort_keys=False)
        record_profile_after_admin_save(out)
        updated.append(p.name)

    profile_manager.invalidate()
    profile_manager.load_all_if_stale(force=True)
    skill_registry.reload()
    return {"status": "success", "name": new, "profiles": updated}


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
    skill_registry.unhide(s.name)
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


_OAUTH_DISCOVERED_ENDPOINT_KEYS = (
    "authorization_endpoint",
    "registration_endpoint",
    "resource",
)


def _oauth_config_for_admin(raw_json: Optional[str]) -> Dict[str, Any]:
    """oauth_config per la risposta admin: il client_secret non esce mai in chiaro."""
    try:
        cfg = json.loads(raw_json or "{}")
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    secret_set = bool(str(cfg.pop("client_secret", "") or "").strip())
    cfg.pop("client_secret_encrypted", None)
    cfg["client_secret"] = ""
    cfg["client_secret_set"] = secret_set
    return cfg


def _merge_admin_oauth_config(
    stored_json: Optional[str], incoming: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Unisce l'oauth_config inviato dall'admin con quello salvato.

    - ``{}`` azzera la configurazione.
    - Valori vuoti non sovrascrivono (il form non conosce gli endpoint scoperti a
      runtime e riceve il client_secret mascherato), tranne ``client_id`` che si può
      svuotare esplicitamente per tornare alla registrazione dinamica.
    - Un client_id cambiato o svuotato invalida secret e provenienza precedenti.
    - Un authorization_server cambiato invalida gli endpoint scoperti e un client
      ottenuto via registrazione dinamica.
    """
    if not incoming:
        return {}
    try:
        stored = json.loads(stored_json or "{}")
    except Exception:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    merged = dict(stored)

    old_as = str(stored.get("authorization_server") or "").strip()
    new_as = str(incoming.get("authorization_server") or "").strip()
    stale_dynamic_id = ""
    if new_as and old_as and new_as != old_as:
        for key in _OAUTH_DISCOVERED_ENDPOINT_KEYS:
            merged.pop(key, None)
        if stored.get("client_id_source") == "dynamic_registration":
            stale_dynamic_id = str(stored.get("client_id") or "").strip()
            for key in ("client_id", "client_secret", "client_id_source"):
                merged.pop(key, None)

    if "client_id" in incoming:
        new_id = str(incoming.get("client_id") or "").strip()
        if new_id and new_id == stale_dynamic_id:
            # Il form rimanda il client dinamico del vecchio server: non vale più.
            new_id = ""
        if new_id != str(merged.get("client_id") or "").strip():
            merged.pop("client_secret", None)
            merged.pop("client_id_source", None)
        if new_id:
            merged["client_id"] = new_id
        else:
            merged.pop("client_id", None)

    for key, value in incoming.items():
        if key in ("client_id", "client_secret_set", "client_id_source"):
            continue
        if value in (None, "", [], {}):
            continue
        merged[key] = value
    return merged


def _mcp_integration_to_dict(
    r: McpServerConfig, *, in_registry: bool
) -> Dict[str, Any]:
    from ..runtime.mcp_integration_integrity import (
        build_suggested_env_yaml_block,
        enrich_credential_schema_with_env_placeholders,
    )

    from ..runtime.mcp_integration_helpers import strip_oauth_user_fields_for_server

    mode = getattr(r, "credential_mode", None) or "none"
    schema = json.loads(r.credential_schema_json or "[]")
    schema = strip_oauth_user_fields_for_server(
        schema,
        r.server_slug,
        mcp_manager.get_server_config(r.server_slug),
        connector_id=getattr(r, "aion_connector_id", None),
    )
    schema = enrich_credential_schema_with_env_placeholders(
        schema, r.server_slug, credential_mode=mode
    )
    return {
        "id": r.id,
        "server_slug": r.server_slug,
        "display_name": r.display_name,
        "description": r.description,
        "icon_url": r.icon_url,
        "category": r.category,
        "is_enabled_for_users": r.is_enabled_for_users,
        "requires_user_credentials": r.requires_user_credentials,
        "credential_mode": mode,
        "aion_connector_id": getattr(r, "aion_connector_id", None),
        "user_may_disable": bool(getattr(r, "user_may_disable", True)),
        "credential_schema": schema,
        "oauth_config": _oauth_config_for_admin(r.oauth_config_json),
        "is_in_registry": in_registry,
        "suggested_env_yaml": build_suggested_env_yaml_block(
            r.server_slug, schema, credential_mode=mode
        ),
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
            oauth_config_json=json.dumps(
                _merge_admin_oauth_config(None, body.oauth_config or {})
            ),
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
                from ..runtime.mcp_integration_helpers import (
                    strip_oauth_user_fields_for_server,
                )

                row.credential_schema_json = json.dumps(
                    strip_oauth_user_fields_for_server(
                        body.credential_schema,
                        server_slug,
                        mcp_manager.get_server_config(server_slug),
                        connector_id=row.aion_connector_id,
                    )
                )
        if body.oauth_config is not None:
            row.oauth_config_json = json.dumps(
                _merge_admin_oauth_config(row.oauth_config_json, body.oauth_config)
            )
        if body.user_may_disable is not None:
            row.user_may_disable = body.user_may_disable
        row.updated_at = datetime.now(timezone.utc)
        mode_after = row.credential_mode or "none"
        await session.commit()

    if body.apply_suggested_env and mode_after in ("per_user", "org_shared"):
        schema_for_env = None
        if body.schema_override and body.credential_schema is not None:
            from ..runtime.mcp_integration_helpers import (
                strip_oauth_user_fields_for_server,
            )

            schema_for_env = strip_oauth_user_fields_for_server(
                body.credential_schema,
                server_slug,
                mcp_manager.get_server_config(server_slug),
                connector_id=getattr(row, "aion_connector_id", None) if row else None,
            )
        elif row and row.credential_schema_json:
            try:
                schema_for_env = json.loads(row.credential_schema_json)
            except Exception:
                schema_for_env = None
        merge_suggested_env_into_registry(
            server_slug,
            mode_after,
            credential_schema=schema_for_env,
            force_replace_schema_env=True,
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
    import logging as _logging

    _log = _logging.getLogger("aion.admin.advise")

    try:
        from src.runtime.llm_adapter import resolve_llm_credentials

        base, model, token = resolve_llm_credentials()
        if not base.endswith("/v1"):
            base = base + "/v1" if "/v1" not in base else base.split("/v1")[0] + "/v1"
        base.rstrip("/") + "/chat/completions"
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
    db_schema = None
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
        if row and row.credential_schema_json:
            try:
                db_schema = json.loads(row.credential_schema_json)
            except Exception:
                db_schema = None

    result = await apply_integration_config(
        server_slug,
        credential_mode=credential_mode,
        credential_schema=db_schema,
        schema_override=bool(db_schema),
        apply_suggested_env=True,
        force_replace_schema_env=True,
        sync_db=False,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Failed"))
    return result


@router.delete("/mcp-integrations/{server_slug}")
async def admin_delete_mcp_integration(server_slug: str):
    from ..runtime.mcp_integration_integrity import delete_mcp_user_data

    cleanup = await delete_mcp_user_data(server_slug)
    async with get_async_session_maker()() as session:
        await session.execute(
            delete(McpServerConfig).where(McpServerConfig.server_slug == server_slug)
        )
        await session.commit()
    return {"ok": True, "cleanup": cleanup}


@router.get("/mcp/integrity")
async def admin_mcp_integrity():
    from ..runtime.mcp_integration_integrity import scan_mcp_integrity

    return await scan_mcp_integrity()


@router.post("/mcp/integrity/repair")
async def admin_mcp_integrity_repair(body: Dict[str, Any]):
    from ..runtime.mcp_integration_integrity import repair_mcp_integrity_issue

    issue = body.get("issue")
    if not isinstance(issue, dict):
        raise HTTPException(status_code=400, detail="issue object required")
    result = await repair_mcp_integrity_issue(issue)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400, detail=result.get("error", "repair failed")
        )
    return result


@router.post("/mcp/integrity/repair-all")
async def admin_mcp_integrity_repair_all():
    from ..runtime.mcp_integration_integrity import (
        repair_mcp_integrity_issue,
        scan_mcp_integrity,
    )

    report = await scan_mcp_integrity()
    repaired = []
    failed = []
    env_repair_slugs: set[str] = set()
    for issue in report.get("issues", []):
        repair = issue.get("repair")
        slug = str(issue.get("server_slug") or "")
        if repair not in (
            "purge_credentials",
            "purge_preferences",
            "delete_policy",
            "migrate_credentials",
            "apply_suggested_env",
            "sync_from_registry",
        ):
            continue
        if repair == "apply_suggested_env":
            if not slug or slug in env_repair_slugs:
                continue
            env_repair_slugs.add(slug)
        try:
            result = await repair_mcp_integrity_issue(issue)
            if result.get("ok"):
                repaired.append(
                    {
                        "issue": issue.get("code"),
                        "server_slug": issue.get("server_slug"),
                        **result,
                    }
                )
            else:
                failed.append(
                    {
                        "issue": issue.get("code"),
                        "server_slug": issue.get("server_slug"),
                        "error": result.get("error", "repair failed"),
                    }
                )
        except Exception as exc:
            failed.append(
                {
                    "issue": issue.get("code"),
                    "server_slug": issue.get("server_slug"),
                    "error": str(exc),
                }
            )
    return {"repaired": repaired, "failed": failed, "count": len(repaired)}


@router.get("/market/search")
async def search_market(q: str = ""):
    """Searches across integrated MCP marketplaces (Smithery, Glama, GitHub, etc.)."""
    return hub_aggregator.search_all(q)


@router.get("/market/config")
async def get_market_config(
    qualified_name: Optional[str] = None,
    item_id: Optional[str] = None,
):
    """Recupera lo schema di configurazione normalizzato per un server MCP (Smithery o registry)."""
    target_name = qualified_name or item_id or ""
    if not target_name:
        raise HTTPException(
            status_code=400, detail="qualified_name o item_id obbligatorio"
        )

    from ..marketplaces.smithery_client import (
        get_smithery_server_details,
        extract_normalized_envs_from_schema,
        has_smithery_proprietary_auth,
    )

    details = get_smithery_server_details(target_name)
    if not details:
        raise HTTPException(
            status_code=404, detail=f"Dettagli non trovati per {target_name}"
        )

    if has_smithery_proprietary_auth(details, target_name):
        raise HTTPException(
            status_code=400,
            detail=f"Il server {target_name} richiede autenticazione proprietaria Smithery OAuth e non può essere installato. Smithery è utilizzabile solo come catalogo.",
        )

    normalized_envs = extract_normalized_envs_from_schema(details)
    connections = details.get("connections") or []
    runtime = "node"
    deployment_url = (details.get("deploymentUrl") or "").strip()

    # Ignora proxy proprietari Smithery (*.run.tools / smithery.ai)
    if "run.tools" in deployment_url.lower() or "smithery.ai" in deployment_url.lower():
        deployment_url = ""

    is_remote = False

    if (
        connections
        and isinstance(connections, list)
        and isinstance(connections[0], dict)
    ):
        runtime = connections[0].get("runtime") or "node"
        conn_dep = (connections[0].get("deploymentUrl") or "").strip()
        if (
            conn_dep
            and "run.tools" not in conn_dep.lower()
            and "smithery.ai" not in conn_dep.lower()
        ):
            deployment_url = conn_dep
        if connections[0].get("type") in ("http", "sse") and deployment_url:
            is_remote = True

    q_name = (details.get("qualifiedName") or target_name).strip()
    auth_type = "oauth2"
    credential_mode = "per_user"

    if is_remote and deployment_url:
        install_type = "remote"
        runner = "node"
        command_args = ["node_modules/mcp-remote/dist/proxy.js", deployment_url]
        package_url = deployment_url

        try:
            from ..mcp_credential_discovery import probe_remote_url_sync
            import asyncio

            probe_info = await asyncio.to_thread(
                probe_remote_url_sync, deployment_url, {}
            )
            if probe_info:
                auth_type = probe_info.get("type") or "oauth2"
                credential_mode = probe_info.get("credential_mode") or (
                    "per_user" if auth_type == "oauth2" else "org_shared"
                )
                if not normalized_envs and probe_info.get("credential_schema"):
                    for item in probe_info["credential_schema"]:
                        normalized_envs.append(
                            {
                                "key": item.get("key") or "OAUTH_TOKEN",
                                "description": item.get("label")
                                or f"Token per {q_name}",
                                "required": bool(item.get("required", True)),
                                "is_secret": True,
                                "default": "",
                                "type": "password",
                            }
                        )
        except Exception as exc:
            logger.debug(
                "Probe remote url for market/config failed (%s): %s",
                deployment_url,
                exc,
            )
    else:
        install_type = "zero-install"
        runner = "uvx" if runtime == "python" else "npx"
        clean_pkg = (
            q_name.split("/")[-1]
            if ("/" in q_name and not q_name.startswith("@"))
            else q_name
        )
        if runtime == "python":
            runner = "uvx"
            command_args = [clean_pkg]
            package_url = clean_pkg
        else:
            runner = "npx"
            command_args = ["-y", clean_pkg]
            package_url = clean_pkg

    return {
        "qualified_name": q_name,
        "display_name": details.get("displayName") or target_name,
        "description": details.get("description") or "",
        "icon_url": details.get("iconUrl") or "",
        "runtime": runtime,
        "runner": runner,
        "is_remote": is_remote,
        "install_type": install_type,
        "deployment_url": deployment_url,
        "remote_url": deployment_url if is_remote else "",
        "auth_type": auth_type,
        "credential_mode": credential_mode,
        "package_url": package_url,
        "command_args": command_args,
        "required_envs": normalized_envs,
    }


class GitHubAnalyzeBody(BaseModel):
    url: str = Field(..., description="URL repository GitHub")


@router.post("/market/analyze-github")
async def analyze_github_endpoint(body: GitHubAnalyzeBody):
    """Analizza un repository GitHub MCP senza clonare su disco tramite LLM Structured Output."""
    from ..marketplaces.github_raw_analyzer import analyze_github_mcp_repo

    try:
        res = await analyze_github_mcp_repo(body.url)
        return {
            "status": "success",
            "package_url": res.package_url,
            "runner": res.runner,
            "description": res.description,
            "command_args": res.command_args,
            "required_envs": [
                {
                    "key": e.key,
                    "description": e.description,
                    "is_secret": e.is_secret,
                    "required": e.required,
                    "default": e.default,
                }
                for e in res.required_envs
            ],
            "cli_args": [
                {
                    "name": a.name,
                    "description": a.description,
                    "required": a.required,
                    "default": a.default,
                    "placeholder": a.placeholder,
                }
                for a in res.cli_args
            ],
        }
    except Exception as exc:
        logger.exception("analyze-github failed for %s", body.url)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ZeroInstallRequest(BaseModel):
    server_slug: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    runner: str = "npx"  # "npx" | "uvx" | "node"
    package_url: str
    envs: Dict[str, str] = Field(default_factory=dict)
    secret_keys: List[str] = Field(default_factory=list)
    schema_fields: Optional[List[Dict[str, Any]]] = None
    command_args: Optional[List[str]] = None
    icon_url: Optional[str] = None
    # github_source: se True, i command_args vanno rispettati così come sono
    github_source: bool = False
    # credential_mode: "none" | "org_shared" (condivise organizzazione) | "per_user" (personali)
    credential_mode: Optional[str] = "org_shared"
    is_remote: bool = False
    remote_url: Optional[str] = None
    auth_type: Optional[str] = None
    enabled_tools: Optional[List[str]] = None


@router.post("/market/install-zero")
async def install_zero_endpoint(body: ZeroInstallRequest):
    """Installa un MCP server in modalità Zero-Install o Remote-Bridge salvando i secret cifrati in aion.db."""
    import re
    from ..runtime.credential_store import set_credential
    from ..data.engine import get_async_session_maker
    from ..data.models import McpServerConfig
    from ..data.ids import new_uuid7_str
    from sqlalchemy import select

    raw_slug = (body.server_slug or "").strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "_", raw_slug).strip("_")
    if not slug:
        slug = "mcp_custom"

    runner = body.runner.strip().lower()
    if runner not in ("npx", "uvx", "node", "remote"):
        runner = "npx"

    pkg = body.package_url.strip()
    if not pkg:
        pkg = slug

    is_remote_server = (
        body.is_remote
        or bool(body.remote_url)
        or runner in ("remote", "remote-bridge")
        or pkg.startswith(("http://", "https://"))
    )

    if is_remote_server:
        remote_url = (body.remote_url or pkg).strip()
        auth_type = (body.auth_type or "oauth2").strip().lower()
        if auth_type not in ("none", "oauth2", "api-key", "basic"):
            auth_type = "oauth2"

        cred_mode = (body.credential_mode or "").strip().lower()
        if cred_mode not in ("org_shared", "per_user", "none"):
            cred_mode = (
                "per_user"
                if auth_type == "oauth2"
                else ("org_shared" if auth_type != "none" else "none")
            )

        from ..mcp_integration_sync import (
            sync_mcp_server_config_from_registry,
            suggest_registry_env_for_per_user,
            suggest_registry_env_for_org_shared,
        )

        schema_fields: List[Dict[str, Any]] = []
        if body.schema_fields:
            for sf in body.schema_fields:
                k = str(sf.get("key") or "").strip()
                if not k:
                    continue
                is_sec = sf.get("is_secret", True)
                req_val = sf.get("required")
                schema_fields.append(
                    {
                        "key": k,
                        "label": sf.get("label")
                        or sf.get("description")
                        or k.replace("_", " ").title(),
                        "required": bool(req_val) if req_val is not None else True,
                        "is_secret": is_sec,
                        "type": "password" if is_sec else "text",
                    }
                )
        elif auth_type != "none":
            auth_key = (
                "OAUTH_TOKEN"
                if auth_type == "oauth2"
                else ("API_KEY" if auth_type == "api-key" else "BASIC_AUTH")
            )
            schema_fields.append(
                {
                    "key": auth_key,
                    "label": "Token OAuth"
                    if auth_type == "oauth2"
                    else ("Chiave API" if auth_type == "api-key" else "Basic Auth"),
                    "required": True,
                    "is_secret": True,
                    "type": "password",
                }
            )

        # Build remote bridge config with the selected credential mode
        remote_config = build_remote_bridge_registry_config(
            remote_url,
            slug,
            body.description or f"MCP remoto connesso a {remote_url}",
            auth_type=auth_type,
            credential_mode=cred_mode,
        )

        # Build clean environment map according to credential mode
        if cred_mode == "per_user":
            env_map = suggest_registry_env_for_per_user(slug, schema_fields)
            remote_config["env"] = {**remote_config.get("env", {}), **env_map}
        elif cred_mode == "org_shared":
            env_map = suggest_registry_env_for_org_shared(schema_fields)
            remote_config["env"] = {**remote_config.get("env", {}), **env_map}
            for k, val in (body.envs or {}).items():
                key_clean = str(k).strip()
                val_str = str(val).strip()
                if key_clean and val_str:
                    await set_credential(
                        "default", slug, key_clean, val_str, tenant_id="default"
                    )
                    await set_credential(
                        "org_shared", slug, key_clean, val_str, tenant_id="default"
                    )
                    remote_config["env"][key_clean] = f"${{{key_clean}}}"
        else:  # none
            remote_config["env"] = {}

        # Registra in mcp_registry.local.yaml
        mcp_manager.load_registry()
        config: Dict[str, Any] = {
            "description": (body.description or f"MCP remoto {slug}")[:2000],
            "source_id": f"remote:{slug}",
            "remotes": [{"type": "sse", "url": remote_url}],
            "aion_market_install": "remote",
            **remote_config,
        }
        mcp_manager._registry_local[slug] = config
        mcp_manager._rebuild_merged()
        mcp_manager.save_registry()

        async with get_async_session_maker()() as session:
            existing = (
                await session.execute(
                    select(McpServerConfig).where(McpServerConfig.server_slug == slug)
                )
            ).scalar_one_or_none()

            schema_json = json.dumps(schema_fields)

            if existing:
                existing.display_name = body.display_name or slug
                existing.description = body.description or ""
                existing.is_enabled_for_users = True
                existing.credential_mode = cred_mode
                existing.requires_user_credentials = cred_mode == "per_user"
                existing.credential_schema_json = schema_json
                if body.icon_url:
                    existing.icon_url = body.icon_url
            else:
                cfg_row = McpServerConfig(
                    id=new_uuid7_str(),
                    server_slug=slug,
                    display_name=body.display_name or slug,
                    description=body.description or "",
                    icon_url=body.icon_url,
                    is_enabled_for_users=True,
                    requires_user_credentials=(cred_mode == "per_user"),
                    credential_mode=cred_mode,
                    credential_schema_json=schema_json,
                )
                session.add(cfg_row)
            await session.commit()

        await sync_mcp_server_config_from_registry(slug)

        return {
            "status": "success",
            "server_slug": slug,
            "display_name": body.display_name or slug,
            "runner": "node",
            "package_url": remote_url,
            "credential_mode": cred_mode,
            "is_remote": True,
            "remote_url": remote_url,
        }

    # Standard Zero-Install (npx / uvx)
    # Se è un pacchetto npm con formato owner/pkg senza @, aggiungi la @ per renderlo uno scoped package valido
    if (
        runner == "npx"
        and "/" in pkg
        and not pkg.startswith("@")
        and not pkg.startswith("http")
    ):
        pkg = f"@{pkg}"

    # Costruisci il comando di esecuzione diretto nativo
    if body.command_args:
        # Se i command_args contengono @smithery/cli run (che richiede login/OAuth interattivo), converti in npx diretto se pacchetto npm valido
        if (
            len(body.command_args) >= 4
            and "@smithery/cli" in str(body.command_args[1])
            and body.command_args[2] == "run"
        ):
            target_pkg = body.command_args[3]
            clean_pkg = (
                f"@{target_pkg}"
                if ("/" in target_pkg and not target_pkg.startswith("@"))
                else target_pkg
            )
            args = ["-y", clean_pkg]
        else:
            args = list(body.command_args)
    elif runner == "uvx":
        clean_pkg = (
            pkg.split("/")[-1] if ("/" in pkg and not pkg.startswith("@")) else pkg
        )
        args = [clean_pkg]
    else:
        clean_pkg = f"@{pkg}" if ("/" in pkg and not pkg.startswith("@")) else pkg
        args = ["-y", clean_pkg]

    cred_mode = (body.credential_mode or "").strip().lower()
    from ..mcp_integration_sync import (
        suggest_registry_env_for_per_user,
        suggest_registry_env_for_org_shared,
    )

    # Costruisci schema_fields
    schema_fields: List[Dict[str, Any]] = []
    if body.schema_fields:
        for sf in body.schema_fields:
            k = str(sf.get("key") or "").strip()
            if not k:
                continue
            is_sec = sf.get("is_secret", True)
            req_val = sf.get("required")
            schema_fields.append(
                {
                    "key": k,
                    "label": sf.get("label")
                    or sf.get("description")
                    or k.replace("_", " ").title(),
                    "required": bool(req_val) if req_val is not None else True,
                    "is_secret": is_sec,
                    "type": "password" if is_sec else "text",
                }
            )

    # Elabora eventuali valori passati in body.envs (aggiungendoli allo schema se non presenti)
    for k, val in body.envs.items():
        key_clean = str(k).strip()
        if not key_clean:
            continue
        is_secret = key_clean in body.secret_keys or any(
            x in key_clean.lower()
            for x in ("key", "token", "secret", "password", "auth", "pwd")
        )

        if not any(f["key"] == key_clean for f in schema_fields):
            schema_fields.append(
                {
                    "key": key_clean,
                    "label": key_clean.replace("_", " ").title(),
                    "required": True,
                    "is_secret": is_secret,
                    "type": "password" if is_secret else "text",
                }
            )

    # Costruisci il dizionario env per il registry in base alla modalità credenziali
    env_dict: Dict[str, str] = {}
    if cred_mode == "per_user":
        # In modalità per_user utilizziamo rigorosamente lo standard ${AION_USER_<SLUG_PREFIX>__<KEY>}
        env_dict = suggest_registry_env_for_per_user(slug, schema_fields)
    elif cred_mode == "org_shared":
        # In modalità org_shared: placeholder ${KEY} per i secret, o valore letterale per i non-secret se specificato
        env_dict = suggest_registry_env_for_org_shared(schema_fields)
        for k, val in body.envs.items():
            key_clean = str(k).strip()
            val_str = str(val).strip()
            if not key_clean or not val_str:
                continue
            is_secret = key_clean in body.secret_keys or any(
                x in key_clean.lower()
                for x in ("key", "token", "secret", "password", "auth", "pwd")
            )
            if is_secret:
                # Salva cifrato in DB sia per "default" che per "org_shared"
                await set_credential(
                    "default", slug, key_clean, val_str, tenant_id="default"
                )
                await set_credential(
                    "org_shared", slug, key_clean, val_str, tenant_id="default"
                )
                env_dict[key_clean] = f"${{{key_clean}}}"
            else:
                env_dict[key_clean] = val_str
    else:
        # None
        env_dict = {}

    # Registra in mcp_registry.local.yaml
    mcp_manager.load_registry()
    config: Dict[str, Any] = {
        "command": runner,
        "args": args,
        "env": env_dict,
        "description": (body.description or f"Zero-Install MCP {slug} via {runner}")[
            :2000
        ],
        "aion_market_install": "zero-install",
        "zero_package": pkg,
    }
    if body.enabled_tools is not None:
        config["enabled_tools"] = [
            str(t).strip() for t in body.enabled_tools if str(t).strip()
        ]
    mcp_manager._registry_local[slug] = config
    mcp_manager._rebuild_merged()
    mcp_manager.save_registry()
    from ..main import clear_agent_cache

    clear_agent_cache()

    # Determina la modalità delle credenziali (org_shared vs per_user)
    cred_mode = (body.credential_mode or "").strip().lower()
    if cred_mode not in ("org_shared", "per_user", "none"):
        cred_mode = (
            "org_shared"
            if body.secret_keys or any(f["is_secret"] for f in schema_fields)
            else "none"
        )

    # Aggiorna record McpServerConfig in DB aion.db
    async with get_async_session_maker()() as session:
        existing = (
            await session.execute(
                select(McpServerConfig).where(McpServerConfig.server_slug == slug)
            )
        ).scalar_one_or_none()

        schema_json = json.dumps(schema_fields)

        if existing:
            existing.display_name = body.display_name or slug
            existing.description = body.description or ""
            existing.is_enabled_for_users = True
            existing.credential_mode = cred_mode
            existing.requires_user_credentials = cred_mode == "per_user"
            existing.credential_schema_json = schema_json
            if body.icon_url:
                existing.icon_url = body.icon_url
        else:
            cfg_row = McpServerConfig(
                id=new_uuid7_str(),
                server_slug=slug,
                display_name=body.display_name or slug,
                description=body.description or "",
                icon_url=body.icon_url,
                is_enabled_for_users=True,
                requires_user_credentials=(cred_mode == "per_user"),
                credential_mode=cred_mode,
                credential_schema_json=schema_json,
            )
            session.add(cfg_row)
        await session.commit()

    return {
        "status": "success",
        "server_slug": slug,
        "display_name": body.display_name or slug,
        "runner": runner,
        "package_url": pkg,
        "credential_mode": cred_mode,
    }


@router.delete("/market/uninstall-zero/{server_slug}")
async def uninstall_zero_endpoint(server_slug: str):
    """Disinstalla un MCP zero-install, rimuove dal registry e cancella i secret da aion.db."""
    from ..data.engine import get_async_session_maker
    from ..data.models import McpServerConfig, UserMcpCredential
    from sqlalchemy import delete

    slug = server_slug.strip()
    mcp_manager.load_registry()
    if slug in mcp_manager._registry_base:
        raise HTTPException(
            status_code=400, detail="Impossibile eliminare i moduli MCP di sistema."
        )

    from ..agent_profile import profile_manager

    profile_manager.load_all()
    referencing_profiles = [
        p.name for p in profile_manager._profiles.values() if slug in p.mcp_servers
    ]
    if referencing_profiles:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "mcp_in_use",
                "message": f"Impossibile eliminare il server MCP. È in uso nei seguenti profili: {', '.join(referencing_profiles)}",
                "profiles": referencing_profiles,
            },
        )

    if slug in mcp_manager._registry_local:
        mcp_manager._registry_local.pop(slug, None)
        mcp_manager._rebuild_merged()
        mcp_manager.save_registry()

    async with get_async_session_maker()() as session:
        await session.execute(
            delete(UserMcpCredential).where(UserMcpCredential.server_slug == slug)
        )
        await session.execute(
            delete(McpServerConfig).where(McpServerConfig.server_slug == slug)
        )
        await session.commit()

    return {"status": "success", "server_slug": slug}


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
async def get_ltm_facts(
    query: str = "",
    scope_type: str = "user",
    scope_key: str = "default",
    tenant_id: str = "default",
    auth: ChatAuthIdentity = Depends(require_admin_role),
):
    """Retrieve semantic facts from Mnemos LTM.

    La memoria ``user`` e' leggibile solo dal proprietario (admin inclusi).
    """
    from src.api.ownership import effective_user_id
    from src.identity import sanitize_user_id
    from src.memory.mnemos.scope import global_scope, project_scope, user_scope
    from src.memory.mnemos import store

    if scope_type not in ("project", "global") and sanitize_user_id(
        scope_key
    ) != effective_user_id(auth):
        raise HTTPException(status_code=404, detail="Scope not found")

    try:
        if scope_type == "project":
            scope = project_scope(tenant_id, scope_key)
        elif scope_type == "global":
            scope = global_scope(tenant_id)
        else:
            scope = user_scope(tenant_id, scope_key)
        if query.strip():
            notes = await store.fts_search(scope, query, limit=20, mode="current")
        else:
            notes = await store.list_notes(scope, limit=20)
        facts = (
            [n.content for n, _ in notes]
            if query.strip()
            else [n.content for n in notes]
        )
        return {"facts": facts, "status": "online", "type": "mnemos"}
    except Exception as e:
        logger.error("Error calling Mnemos: %s", e)
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


class RemoteInstallBody(BaseModel):
    url: str = Field(..., min_length=8, description="URL del server MCP remoto")
    display_name: Optional[str] = None
    auth_type: Optional[str] = Field(
        None,
        description="none | oauth2 | api-key | basic — se assente, rilevato via probe o default oauth2",
    )
    connector_id: Optional[str] = Field(
        None, description="id catalogo connettore (aion_connector_id)"
    )


class RemoteProbeBody(BaseModel):
    url: str = Field(
        ..., min_length=8, description="URL del server MCP remoto da validare"
    )


@router.post("/mcp/probe-remote")
async def probe_remote_mcp(body: RemoteProbeBody):
    """Valida un endpoint MCP remoto (auth, OAuth discovery) senza installare."""
    import asyncio
    from ..mcp_credential_discovery import probe_remote_url_sync

    url = body.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(
            status_code=400, detail="L'URL deve iniziare con http:// o https://"
        )
    try:
        probe = await asyncio.to_thread(probe_remote_url_sync, url, {})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Probe fallito: {exc}") from exc
    return {"ok": True, "url": url, "probe": probe}


@router.post("/market/install-remote")
async def install_from_remote_url(body: RemoteInstallBody):
    """Installa e registra un server MCP remoto da un URL diretto (usando mcp-remote bridge)."""
    import re
    from ..mcp_integration_sync import sync_mcp_server_config_from_registry

    url = body.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(
            status_code=400, detail="L'URL deve iniziare con http:// o https://"
        )

    if not body.display_name:
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

    slug = re.sub(r"[^a-z0-9_-]+", "_", default_name.lower()).strip("_") or "remote_mcp"
    auth_type = str(body.auth_type or "").strip().lower() or "oauth2"
    if auth_type not in ("none", "oauth2", "api-key", "basic"):
        auth_type = "oauth2"

    remote_config = build_remote_bridge_registry_config(
        url, slug, f"MCP remoto connesso a {url}", auth_type=auth_type
    )
    mcp_manager.load_registry()
    config = {
        "description": f"MCP remoto connesso a {url}",
        "source_id": f"remote:{slug}",
        "remotes": [{"type": "sse", "url": url}],
        **remote_config,
    }
    if body.connector_id:
        config["aion_connector_id"] = body.connector_id.strip()

    mcp_manager._registry_local[slug] = config
    mcp_manager._rebuild_merged()
    mcp_manager.save_registry()
    await sync_mcp_server_config_from_registry(slug)

    return {"status": "success", "name": slug, "server_slug": slug, "url": url}


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


@router.post("/mcp/{name}/probe")
async def probe_mcp_server(
    name: str,
    auth: ChatAuthIdentity = Depends(require_admin_role),
):
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
                    "error_type": "executable_missing",
                    "error": "Node.js executable ('node') not found on system PATH.",
                    "hint": "Install Node.js on the host to run remote-bridge MCP servers.",
                    "tools": [],
                    "tool_count": 0,
                }
        else:
            if not shutil.which("npx"):
                return {
                    "ok": False,
                    "server_slug": name,
                    "error_type": "executable_missing",
                    "error": "npx command not found and local mcp-remote not installed.",
                    "hint": "Install Node.js/npm on the host or build node_modules.",
                    "tools": [],
                    "tool_count": 0,
                }

    # Clear previous recorded probe errors for this server and reset probe pool session
    clear_mcp_load_errors("mcp-probe", name)
    await mcp_manager.release_session("mcp-probe")

    try:
        from src.identity import sanitize_user_id
        from src.runtime.credential_store import resolve_mcp_env_for_user

        probe_user_id = sanitize_user_id(auth.identifier or auth.user_row_id or None)
        probe_cfg = dict(cfg)
        template_env = (
            probe_cfg.get("env") if isinstance(probe_cfg.get("env"), dict) else {}
        )
        resolved_env = await resolve_mcp_env_for_user(
            template_env,
            user_id=probe_user_id,
            tenant_id="default",
            server_slug=name,
        )
        probe_env, missing_secrets = merge_probe_env(template_env, resolved_env)
        if missing_secrets:
            return {
                "ok": False,
                "server_slug": name,
                "error_type": "auth_failed",
                "error": "Per-user OAuth or API secret is not available for this admin user.",
                "hint": (
                    "Connect the integration in chat-ui with the same user that is "
                    "running this probe. The probe no longer sends a placeholder token."
                ),
                "tools": [],
                "tool_count": 0,
            }
        if template_env:
            probe_cfg["env"] = probe_env

        tools = await build_mcp_tools(
            name, probe_cfg, session_id="mcp-probe", user_id=probe_user_id
        )

        enabled_tools_list = cfg.get("enabled_tools")
        enabled_set = (
            set(enabled_tools_list)
            if isinstance(enabled_tools_list, (list, set, tuple))
            else None
        )

        # Controlliamo se sono stati scoperti tool validi
        if tools and len(tools) > 0:
            return {
                "ok": True,
                "server_slug": name,
                "tool_count": len(tools),
                "enabled_tools": enabled_tools_list,
                "tools": [
                    {
                        "name": getattr(tool_item, "name", ""),
                        "description": getattr(tool_item, "description", "") or "",
                        "enabled": (
                            enabled_set is None
                            or getattr(tool_item, "name", "") in enabled_set
                        ),
                    }
                    for tool_item in tools
                ],
            }

        # Se sono stati scoperti 0 tool, verifichiamo se build_mcp_tools ha registrato un errore
        recorded_errors = get_last_mcp_load_errors("mcp-probe")
        raw_error = recorded_errors.get(name)

        if raw_error:
            classified = classify_mcp_error(raw_error, cfg)
            return {
                "ok": False,
                "server_slug": name,
                "error_type": classified["error_type"],
                "error": classified["error"],
                "hint": classified["hint"],
                "raw_error": raw_error,
                "tools": [],
                "tool_count": 0,
            }

        if t == "in_process":
            return {
                "ok": True,
                "server_slug": name,
                "tool_count": 0,
                "note": "Native in-process server: tools are registered directly in the API runtime.",
                "tools": [],
            }

        # 0 tools trovati e nessun crash esplicito: connessione riuscita ma schema vuoto
        return {
            "ok": False,
            "server_slug": name,
            "error_type": "empty_tools",
            "error": "The MCP server connected successfully, but registered 0 tools.",
            "hint": "Check if this MCP requires specific configuration arguments or environment flags to expose tools.",
            "tools": [],
            "tool_count": 0,
        }

    except Exception:
        logger.exception("MCP probe failed for %s", name)
        return {
            "ok": False,
            "server_slug": name,
            "error_type": "probe_failed",
            "error": "MCP probe failed. Check server logs for details.",
            "hint": "Verify MCP server configuration and try again.",
            "tools": [],
            "tool_count": 0,
        }


class ToolsConfigBody(BaseModel):
    enabled_tools: Optional[List[str]] = None


@router.post("/mcp/{name}/tools-config")
async def set_mcp_tools_config(name: str, body: ToolsConfigBody):
    """Imposta la lista dei tool abilitati (enabled_tools) per un server MCP."""
    from ..main import clear_agent_cache

    mcp_manager.load_registry()
    if name not in mcp_manager._registry:
        raise HTTPException(
            status_code=404, detail=f"Server MCP '{name}' non trovato nel registry"
        )

    cfg = mcp_manager._registry_local.get(name) or dict(
        mcp_manager._registry.get(name) or {}
    )
    if body.enabled_tools is not None:
        clean_list = [str(t).strip() for t in body.enabled_tools if str(t).strip()]
        cfg["enabled_tools"] = clean_list
    else:
        cfg.pop("enabled_tools", None)

    mcp_manager._registry_local[name] = cfg
    mcp_manager._rebuild_merged()
    mcp_manager.save_registry()
    clear_agent_cache()

    return {
        "status": "success",
        "server_slug": name,
        "enabled_tools": cfg.get("enabled_tools"),
    }


class CandidateProbeBody(BaseModel):
    runner: str = "npx"
    package_url: str
    command_args: Optional[List[str]] = None
    envs: Dict[str, str] = Field(default_factory=dict)
    secret_keys: List[str] = Field(default_factory=list)
    is_remote: bool = False
    remote_url: Optional[str] = None
    auth_type: Optional[str] = None


@router.post("/market/probe-candidate")
async def probe_candidate_endpoint(body: CandidateProbeBody):
    """Esegue un probe temporaneo su una configurazione candidata MCP prima di salvarla."""
    from ..main import build_mcp_tools

    runner = body.runner.strip().lower()
    if runner not in ("npx", "uvx", "node", "remote"):
        runner = "npx"

    pkg = body.package_url.strip()
    is_remote_server = (
        body.is_remote
        or bool(body.remote_url)
        or runner in ("remote", "remote-bridge")
        or pkg.startswith(("http://", "https://"))
    )

    if is_remote_server:
        remote_url = (body.remote_url or pkg).strip()
        temp_cfg: Dict[str, Any] = {
            "command": "node",
            "args": ["node_modules/mcp-remote/dist/proxy.js", remote_url],
            "type": "remote-bridge",
            "remote_url": remote_url,
            "env": dict(body.envs),
        }
    else:
        if (
            runner == "npx"
            and "/" in pkg
            and not pkg.startswith("@")
            and not pkg.startswith("http")
        ):
            pkg = f"@{pkg}"
        extra_args = list(body.command_args) if body.command_args else []
        if runner == "uvx":
            clean_pkg = (
                pkg.split("/")[-1] if ("/" in pkg and not pkg.startswith("@")) else pkg
            )
            if extra_args and extra_args[0] == clean_pkg:
                args = extra_args
            else:
                args = [clean_pkg] + extra_args
        else:
            clean_pkg = f"@{pkg}" if ("/" in pkg and not pkg.startswith("@")) else pkg
            if extra_args and (
                extra_args[0] == clean_pkg
                or (len(extra_args) > 1 and extra_args[1] == clean_pkg)
            ):
                args = extra_args
            else:
                args = ["-y", clean_pkg] + extra_args
        temp_cfg = {
            "command": runner,
            "args": args,
            "env": dict(body.envs),
        }

    mcp_manager._registry["__candidate_probe__"] = temp_cfg
    try:
        tools = await build_mcp_tools(
            "__candidate_probe__",
            temp_cfg,
            session_id="mcp-probe-candidate",
            user_id="admin-probe",
        )
        if tools and len(tools) > 0:
            return {
                "ok": True,
                "tool_count": len(tools),
                "tools": [
                    {
                        "name": getattr(tool_item, "name", ""),
                        "description": getattr(tool_item, "description", "") or "",
                    }
                    for tool_item in tools
                ],
            }
        recorded_errors = get_last_mcp_load_errors("mcp-probe-candidate")
        raw_error = recorded_errors.get("__candidate_probe__")
        return {
            "ok": False,
            "error": raw_error or "Nessun tool rilevato durante il test.",
            "tool_count": 0,
            "tools": [],
        }
    except Exception:
        logger.exception("Candidate probe failed")
        return {
            "ok": False,
            "error": "Candidate probe failed. Check server logs for details.",
            "tool_count": 0,
            "tools": [],
        }
    finally:
        mcp_manager._registry.pop("__candidate_probe__", None)
        await mcp_manager.release_session("mcp-probe-candidate")


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


def _model_name_resolver(providers) -> Any:
    """Map a conversation's ``metadata_json`` to the LLM provider display name."""
    names = {p.slug: p.display_name for p in providers}
    default = next((p for p in providers if p.is_default), None)
    default_name = default.display_name if default else "Default Model"

    def resolve(meta_str: Optional[str]) -> str:
        try:
            slug = json.loads(meta_str or "{}").get("llm_provider_name")
        except Exception:
            slug = None
        return names.get(slug, default_name) if slug else default_name

    return resolve


@router.get("/stats")
async def get_stats():
    """Aggregates system-wide statistics for the dashboard."""
    profiles = profile_manager.list_profiles()

    skill_registry.reload()
    skills_count = len(skill_registry.get_all_names())

    mcp_count = len(mcp_manager._registry)

    # Calculate scheduled jobs
    jobs_total = 0
    jobs_enabled = 0
    model_usage = {}
    projects_total = 0

    from ..data.models import (
        Conversation,
        LlmProvider,
        ScheduledJob,
        SqlQueryProject,
    )
    from sqlalchemy import select

    try:
        async with get_async_session_maker()() as session:
            # 1) Get all providers to resolve slugs to display names
            providers_query = select(LlmProvider)
            providers = (await session.execute(providers_query)).scalars().all()
            model_of = _model_name_resolver(providers)

            # 2) Get all conversations metadata
            conv_query = select(Conversation.metadata_json)
            convs = (await session.execute(conv_query)).scalars().all()

            for meta_str in convs:
                name = model_of(meta_str)
                model_usage[name] = model_usage.get(name, 0) + 1

            # 3) Get scheduled jobs
            jobs_rows = (await session.execute(select(ScheduledJob))).scalars().all()
            jobs_total = len(jobs_rows)
            jobs_enabled = sum(1 for j in jobs_rows if j.enabled)

            # 4) Get SQL query projects count
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
    from ..runtime.mcp_integration_integrity import delete_mcp_user_data

    cleanup = await delete_mcp_user_data(name)
    # Pulisci anche la riga McpServerConfig (policy) se presente
    async with get_async_session_maker()() as session:
        await session.execute(
            delete(McpServerConfig).where(McpServerConfig.server_slug == name)
        )
        await session.commit()
    return {"status": "success", "cleanup": cleanup}


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


class UserCreate(BaseModel):
    # Nessuna password scelta dall'admin: link d'invito via email, oppure (senza
    # SMTP) password temporanea da cambiare al primo login. Email obbligatoria
    # solo con SMTP configurato.
    identifier: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    tenant_id: str = "default"
    roles: List[str] = []
    # Policy API key personali (create dall'utente in chat-ui).
    can_create_api_keys: bool = False
    max_api_keys: int = Field(5, ge=1, le=100)
    api_key_max_ttl_days: int = Field(90, ge=1, le=3650)


class UserUpdate(BaseModel):
    # La password non si imposta da qui: POST /admin/users/{id}/password-link.
    display_name: Optional[str] = None
    email: Optional[str] = None
    roles: Optional[List[str]] = None
    must_change_password: Optional[bool] = None
    can_create_api_keys: Optional[bool] = None
    max_api_keys: Optional[int] = Field(None, ge=1, le=100)
    api_key_max_ttl_days: Optional[int] = Field(None, ge=1, le=3650)


class UserProfilesUpdate(BaseModel):
    allowed_profiles: List[str]


def _valid_email_or_422(value: Optional[str]) -> str:
    from ..auth.password_setup import normalize_email

    email = normalize_email(value)
    if not email:
        raise HTTPException(status_code=422, detail={"code": "invalid_email"})
    return email


def _confirmed_on(idents, provider: Optional[str], since) -> bool:
    """True se una delle identita' SSO e' confermata sul provider attivo."""
    from ..auth.sso.login_mode import is_identity_confirmed

    return bool(
        provider
        and any(
            i.provider == provider and is_identity_confirmed(i, since) for i in idents
        )
    )


@router.get("/users")
async def list_users():
    """List all users in the unified database."""
    from ..data.models import User, UserSsoIdentity
    from ..data.user_password import get_roles
    from ..auth.sso.login_mode import get_login_settings

    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()
    settings = await get_login_settings(tenant)
    login_mode = settings.get("login_mode") or "password"
    provider = settings.get("sso_provider")
    since = settings.get("migration_started_at")

    from ..auth.password_setup import active_links_by_user

    links = await active_links_by_user(tenant)
    async with get_async_session_maker()() as session:
        q = select(User).order_by(User.created_at.desc())
        rows = (await session.execute(q)).scalars().all()
        active_keys = await api_keys_db.count_active_by_user(session)
        identities: Dict[str, list] = {}
        for ident in (await session.execute(select(UserSsoIdentity))).scalars().all():
            identities.setdefault(ident.user_id, []).append(ident)

        def auth_info(r) -> Dict[str, Any]:
            idents = identities.get(r.id, [])
            has_password = r.password_hash is not None
            exempt = bool(getattr(r, "sso_migration_exempt", False))
            confirmed = _confirmed_on(idents, provider, since)
            # Metodo di accesso corrente: in modalita' SSO conta solo il provider
            # attivo se confermato; altrimenti (migrazione non fatta) la password.
            # Le identita' di provider precedenti non sono piu' valide.
            if login_mode != "password" and provider and confirmed:
                login_method = provider
            elif has_password:
                login_method = "password"
            else:
                login_method = None
            link = links.get(r.id)
            temp_expires = r.temp_password_expires_at
            if temp_expires is not None and temp_expires.tzinfo is None:
                temp_expires = temp_expires.replace(tzinfo=timezone.utc)
            return {
                "has_password": has_password,
                "login_method": login_method,
                # Password temporanea (senza SMTP) non ancora cambiata dall'utente.
                "temp_password_pending": temp_expires is not None,
                "temp_password_expires_at": (
                    temp_expires.isoformat() if temp_expires else None
                ),
                # Link email per impostare la password ancora valido (mai il link stesso).
                "setup_link_pending": link is not None,
                "setup_link_purpose": link["purpose"] if link else None,
                "setup_link_expires_at": link["expires_at"] if link else None,
                "setup_link_send_error": link["send_error"] if link else None,
                "sso_providers": sorted({i.provider for i in idents}),
                "sso_migration_exempt": exempt,
                # Da migrare: SSO attivo, ha ancora la password (o un link per
                # impostarla), non esonerato e non ha confermato l'identita'
                # sul provider attivo.
                "migration_pending": bool(
                    login_mode != "password"
                    and provider
                    and (has_password or link is not None)
                    and not exempt
                    and not confirmed
                ),
            }

        return {
            "login_mode": login_mode,
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
                    "totp_enabled": r.totp_enabled_at is not None,
                    "can_create_api_keys": bool(r.can_create_api_keys),
                    "max_api_keys": r.max_api_keys,
                    "api_key_max_ttl_days": r.api_key_max_ttl_days,
                    "api_keys_active": active_keys.get(r.id, 0),
                    "created_at": r.created_at,
                    "last_active_at": r.last_active_at,
                    **auth_info(r),
                }
                for r in rows
            ],
        }


@router.post("/users")
async def create_user(
    body: UserCreate,
    request: Request,
    auth: ChatAuthIdentity = Depends(require_admin_role),
):
    """Crea un utente senza password e gli invia via email il link d'invito.

    L'admin non sceglie e non vede mai la password (ne' il link). Senza SMTP
    l'utente riceve una password temporanea, restituita solo in questa
    risposta, che deve cambiare al primo login.
    """
    from ..auth.password_setup import deliver_password_setup
    from ..auth.sso.login_mode import get_login_settings
    from ..data.audit import record_admin_action
    from ..notifications.smtp_settings import smtp_configured
    from .public_urls import chat_base_url

    # Con SSO attivo gli account nascono solo al primo login SSO
    # (vedi signup policy): niente nuovi utenti con password.
    settings = await get_login_settings(body.tenant_id or "default")
    if settings.get("login_mode", "password") != "password":
        raise HTTPException(
            status_code=409,
            detail={"code": "sso_active_user_creation_disabled"},
        )
    if await smtp_configured(body.tenant_id) or (body.email or "").strip():
        email: Optional[str] = _valid_email_or_422(body.email)
    else:
        email = None
    try:
        uid = await create_invited_user(
            tenant_id=body.tenant_id,
            identifier=body.identifier,
            email=email,
            display_name=body.display_name,
            roles=body.roles or [],
        )
    except UserAlreadyExistsError:
        raise HTTPException(status_code=400, detail="User already exists")
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "identifier_required"})
    from ..data.models import User

    async with get_async_session_maker()() as session:
        u = await session.get(User, uid)
        if u is not None:
            u.can_create_api_keys = body.can_create_api_keys
            u.max_api_keys = body.max_api_keys
            u.api_key_max_ttl_days = body.api_key_max_ttl_days
            await session.commit()

    delivered = await deliver_password_setup(
        body.tenant_id,
        [uid],
        "invite",
        actor_user_id=auth.user_row_id,
        base_url=chat_base_url(request),
    )
    out, audit = _delivery_outcome(delivered, key="invite")
    await record_admin_action(
        tenant_id=body.tenant_id,
        actor=auth.identifier,
        operation="user.create",
        resource_type="user",
        resource_id=uid,
        payload={"identifier": body.identifier, "roles": body.roles, **audit},
    )
    return {"status": "success", "id": uid, **out}


def _link_outcome(links: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Esito di un singolo invio (create user / password-link)."""
    if links["sent"]:
        return {"sent": True, "expires_at": links["sent"][0]["expires_at"]}
    if links["missing_email"]:
        return {"sent": False, "error": "user_email_missing"}
    reason = links["failed"][0].get("reason") if links["failed"] else "smtp_send_failed"
    return {"sent": False, "error": reason}


def _delivery_outcome(
    delivered: Dict[str, Any], *, key: Optional[str]
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Esito di ``deliver_password_setup`` per un solo utente.

    Ritorna ``(risposta, payload_audit)``: la password temporanea compare solo
    nella risposta, mai nell'audit. Con ``key`` l'esito email e' annidato
    (``{"invite": {...}}``), altrimenti e' al primo livello.
    """
    if delivered["delivery"] == "email":
        outcome = _link_outcome(delivered["setup_links"])
        body = {key: outcome} if key else outcome
        return {"delivery": "email", **body}, {"delivery": "email", **body}
    temp = (delivered["temp_passwords"] or [{}])[0]
    expires_at = temp.get("expires_at")
    return (
        {
            "delivery": "temp_password",
            "temp_password": {
                "password": temp.get("password"),
                "expires_at": expires_at,
            },
        },
        {"delivery": "temp_password", "expires_at": expires_at},
    )


@router.post("/users/{user_id}/password-link")
async def send_password_link(
    user_id: str,
    request: Request,
    auth: ChatAuthIdentity = Depends(require_admin_role),
):
    """Invia all'utente un link per (re)impostare la password.

    ``reset`` se ha gia' una password, altrimenti ``invite`` (o ``migration``
    con SSO attivo). La password attuale resta valida finche' l'utente non
    ne sceglie una nuova. Senza SMTP la password viene sostituita subito da
    una temporanea, restituita solo in questa risposta.
    """
    from ..auth.password_setup import deliver_password_setup, user_link_block_reason
    from ..auth.sso.login_mode import get_login_settings, reopen_migration
    from ..data.audit import record_admin_action
    from ..data.models import User
    from ..notifications.smtp_settings import smtp_configured
    from .public_urls import chat_base_url

    async with get_async_session_maker()() as session:
        u = await session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    tenant_id = u.tenant_id or "default"
    blocked = await user_link_block_reason(
        u, needs_email=await smtp_configured(tenant_id)
    )
    if blocked:
        raise HTTPException(status_code=409, detail={"code": blocked})

    sso_mode = (await get_login_settings(tenant_id)).get("login_mode") != "password"
    if u.password_hash:
        purpose = "reset"
    else:
        purpose = "migration" if sso_mode else "invite"
    delivered = await deliver_password_setup(
        tenant_id,
        [user_id],
        purpose,
        actor_user_id=auth.user_row_id,
        base_url=chat_base_url(request),
    )
    out, audit = _delivery_outcome(delivered, key=None)
    # Con SSO attivo l'utente dovra' collegarsi: serve il form password.
    if sso_mode and (out.get("sent") or delivered["delivery"] == "temp_password"):
        await reopen_migration(tenant_id)
    await record_admin_action(
        tenant_id=tenant_id,
        actor=auth.identifier,
        operation=f"user.password_link.{purpose}",
        resource_type="user",
        resource_id=user_id,
        payload=audit,
    )
    return {"status": "success", "purpose": purpose, **out}


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdate,
    auth: ChatAuthIdentity = Depends(require_admin_role),
):
    """Update an existing user."""
    from ..data.models import User
    from ..data.user_password import get_roles, set_roles

    async with get_async_session_maker()() as session:
        u = await session.get(User, user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        if (
            body.roles is not None
            and "admin" in get_roles(u)
            and "admin" not in body.roles
        ):
            if auth.user_row_id == user_id:
                raise HTTPException(
                    status_code=400, detail="You cannot remove your own admin role"
                )
            others = (
                (await session.execute(select(User).where(User.id != user_id)))
                .scalars()
                .all()
            )
            if not any("admin" in get_roles(o) for o in others):
                raise HTTPException(
                    status_code=409, detail="Cannot remove the last administrator"
                )

        if body.display_name is not None:
            u.display_name = body.display_name
        if body.email is not None:
            u.email = _valid_email_or_422(body.email) if body.email.strip() else None
        if body.roles is not None:
            set_roles(u, body.roles)
        if body.must_change_password is not None:
            u.must_change_password = bool(body.must_change_password)
        if body.can_create_api_keys is not None:
            # Disabilitare l'utente revoca subito tutte le sue chiavi attive;
            # quota e durata massima ridotte valgono solo per le nuove chiavi.
            if u.can_create_api_keys and not body.can_create_api_keys:
                await api_keys_db.revoke_all_for_user(session, user_id)
            u.can_create_api_keys = body.can_create_api_keys
        if body.max_api_keys is not None:
            u.max_api_keys = body.max_api_keys
        if body.api_key_max_ttl_days is not None:
            u.api_key_max_ttl_days = body.api_key_max_ttl_days

        await session.commit()

    return {"status": "success"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str):
    """Delete a user."""
    from ..auth.sso.login_mode import (
        _check_migration_completion,
        _invalidate_cache,
        get_login_settings,
    )
    from ..data.models import (
        PasswordSetupToken,
        User,
        UserProfileAccess,
        UserSsoIdentity,
    )

    async with get_async_session_maker()() as session:
        u = await session.get(User, user_id)
        tenant_id = (u.tenant_id if u else None) or "default"
        await session.execute(
            delete(PasswordSetupToken).where(PasswordSetupToken.user_id == user_id)
        )
        # Le FK CASCADE non esistono sui DB SQLite patchati: pulizia esplicita.
        await api_keys_db.delete_all_for_user(session, [user_id])
        # Un'identita' orfana farebbe fallire il primo login SSO successivo
        # della stessa persona (vincolo unico su provider+subject).
        await session.execute(
            delete(UserSsoIdentity).where(UserSsoIdentity.user_id == user_id)
        )
        await session.execute(delete(User).where(User.id == user_id))
        await session.execute(
            delete(UserProfileAccess).where(UserProfileAccess.user_id == user_id)
        )
        await session.commit()

    # Se era l'ultimo utente da migrare, la migrazione SSO si chiude adesso:
    # altrimenti resta "attiva" e blocca i nuovi account con sso_not_linked.
    _invalidate_cache(tenant_id)
    provider = (await get_login_settings(tenant_id)).get("sso_provider")
    if provider:
        await _check_migration_completion(tenant_id, provider)
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


@router.get("/feedback")
async def get_feedback_summary(days: int = Query(7, ge=1, le=365)):
    """Aggregated rating counts per profile and model over the last ``days``.

    Privacy: admins must not read other users' chats, so this endpoint never
    returns message content, feedback comments, prompts or user/conversation ids.
    """
    from datetime import timedelta
    from ..data.models import LlmProvider

    since = datetime.now(timezone.utc) - timedelta(days=days)
    totals = {"positive": 0, "negative": 0}
    by_profile: Dict[str, Dict[str, int]] = {}
    by_model: Dict[str, Dict[str, int]] = {}

    async with get_async_session_maker()() as session:
        providers = (await session.execute(select(LlmProvider))).scalars().all()
        model_of = _model_name_resolver(providers)
        rows = (
            await session.execute(
                select(
                    Message.rating,
                    Message.profile_name,
                    Conversation.profile_slug,
                    Conversation.metadata_json,
                    func.count(),
                )
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(Message.rating.in_((1, -1)), Message.created_at >= since)
                .group_by(
                    Message.rating,
                    Message.profile_name,
                    Conversation.profile_slug,
                    Conversation.metadata_json,
                )
            )
        ).all()

    # Messages store the profile slug; show the profile's display name instead.
    profile_names: Dict[str, str] = {}

    def _profile(raw: str) -> tuple[str, str]:
        p = profile_manager.get_profile(raw)
        slug = p.slug if p else raw
        profile_names.setdefault(slug, (p.name if p and p.name else raw))
        return slug, profile_names[slug]

    for rating, profile_name, profile_slug, meta_str, count in rows:
        key = "positive" if rating == 1 else "negative"
        totals[key] += count
        slug, _ = _profile(profile_name or profile_slug or "default")
        model = model_of(meta_str)
        for bucket, name in ((by_profile, slug), (by_model, model)):
            entry = bucket.setdefault(name, {"positive": 0, "negative": 0})
            entry[key] += count

    def _by_total(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(items, key=lambda r: -(r["positive"] + r["negative"]))

    return {
        "window_days": days,
        "totals": totals,
        "by_profile": _by_total(
            [
                {"profile": profile_names[slug], "slug": slug, **c}
                for slug, c in by_profile.items()
            ]
        ),
        "by_model": _by_total([{"model": name, **c} for name, c in by_model.items()]),
    }


@router.get("/profiling/bottlenecks")
async def get_profiling_bottlenecks():
    """Restituisce le analisi e i colli di bottiglia basati sui JSONL del profiler."""
    from ..profiling.bottleneck import detector

    return detector.detect()
