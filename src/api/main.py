import os
import json
import logging
import asyncio
from contextlib import asynccontextmanager

import src.aion_env  # noqa: F401 — carica `.env` prima delle altre importazioni
from typing import List, Literal, Optional
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, AliasChoices
from sse_starlette.sse import EventSourceResponse

from src.agent_pipeline import AgentPipeline
from src.main import get_agent
from src.identity import sanitize_user_id
from src.runtime.reasoning_effort import effective_reasoning_effort
from src.chart_queue import chart_queue
from src.runtime.redis_client import redis_set_stream_cancel
from .admin import router as admin_router, list_profiles as admin_list_profiles
from .a2a_server import router as a2a_router
from .session_uploads import router as session_uploads_router
from .orchestration import router as orchestration_router
from .research import router as research_router
from .plan_execution import router as plan_execution_router
from .v1 import api_v1_router
from .auth_login import ChatAuthIdentity, require_chat_auth
from .web_search_params import normalize_web_search_restrict_hosts
from src.version import __version__

# Setup Logging
# NOTA: Non aggiungere handler diretti qui — setup_logging() configura tutto (console + OTel).
# Handler diretti su pipeline_logger bypass-ano l'OTLPLogHandler del root logger.
logger = logging.getLogger("aion.api")
# propagate=True (default) → i log salgono al root logger → OTLPLogHandler → SigNoz

for _quiet in (
    "sse_starlette",
    "sse_starlette.sse",
    "aiosqlite",
    "urllib3",
    "urllib3.connectionpool",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "httpx",
    "openai._base_client",
):
    logging.getLogger(_quiet).setLevel(logging.WARNING)


def validate_settings_at_startup() -> None:
    """Validate critical AionSettings values early in the lifespan.

    Logs an error and raises ``RuntimeError`` only for conditions that would
    cause silent incorrect behaviour deep in hot paths.  Non-critical missing
    values emit warnings so the server can still start in dev/test mode.
    """
    from src.settings import get_settings

    s = get_settings()

    if not s.api_url or not s.api_url.strip():
        logger.error(
            "AION_API_URL is not set.  The LLM endpoint URL is required for all "
            "chat requests.  Set it in .env or via the environment variable before "
            "starting the server.  First LLM call will fail with a connection error."
        )
        # Do not raise here — allow the server to start so health/admin endpoints
        # are still reachable.  The chat endpoint will surface the error at runtime.

    if not s.model or not s.model.strip():
        logger.warning(
            "AION_MODEL is not set.  The LLM model name will be empty in API "
            "requests; this may be fine for single-model vLLM deployments but "
            "will fail against multi-model routers (e.g. OpenAI, Azure)."
        )

    if s.chat_max_tokens < 256:
        logger.warning(
            "AION_CHAT_MAX_TOKENS=%d is very low (minimum recommended: 256). "
            "Responses may be truncated.",
            s.chat_max_tokens,
        )

    if s.stm_max_turns < 1:
        logger.warning(
            "AION_STM_MAX_TURNS=%d; setting to 1 would disable STM history. "
            "Increase to at least 4 for a usable conversation window.",
            s.stm_max_turns,
        )

    logger.info(
        "Settings validated: api_url=%r model=%r chat_max_tokens=%d stm_max_turns=%d "
        "context_compress_enabled=%s otel_enabled=%s",
        s.api_url,
        s.model,
        s.chat_max_tokens,
        s.stm_max_turns,
        s.context_compress_enabled,
        s.otel_enabled,
    )


async def _bootstrap_default_admin_user() -> None:
    """Crea un admin di default (``admin``/``admin``) se non esistono ancora
    utenti con ruolo ``admin`` nel tenant.

    Idempotente: gestito dal flag ``AION_SETUP_ADMIN_BOOTSTRAP`` (default
    ``1``). Override credenziali tramite ``AION_SETUP_ADMIN_DEFAULT_IDENTIFIER``
    / ``AION_SETUP_ADMIN_DEFAULT_PASSWORD``. L'utente viene creato con
    ``must_change_password=True`` cosi' che il primo login proponga il
    cambio password (skippabile 24h).
    """
    flag = (os.getenv("AION_SETUP_ADMIN_BOOTSTRAP") or "1").strip().lower()
    if flag not in ("1", "true", "yes"):
        return

    from src.data.user_password import (
        UserAlreadyExistsError,
        admin_exists,
        create_password_user,
    )

    tenant_id = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    if await admin_exists(tenant_id=tenant_id):
        return

    identifier = (
        os.getenv("AION_SETUP_ADMIN_DEFAULT_IDENTIFIER") or "admin"
    ).strip() or "admin"
    password = (
        os.getenv("AION_SETUP_ADMIN_DEFAULT_PASSWORD") or "admin"
    ).strip() or "admin"

    try:
        uid = await create_password_user(
            tenant_id=tenant_id,
            identifier=identifier,
            password=password,
            display_name="Administrator",
            roles=["admin"],
            must_change_password=True,
        )
    except UserAlreadyExistsError:
        return

    logger.warning(
        "Default admin user created (identifier=%r, tenant=%r, id=%s). "
        "Change the password at first login. Disable with "
        "AION_SETUP_ADMIN_BOOTSTRAP=0.",
        identifier,
        tenant_id,
        uid,
    )


def _cleanup_orphaned_mcp_remotes() -> None:
    """Termina i processi mcp-remote orfani rimasti attivi in background da precedenti esecuzioni."""
    import subprocess

    try:
        logger.info("🧹 Rimozione processi mcp-remote orfani...")
        subprocess.run(
            ["pkill", "-f", "mcp-remote"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning(
            "Errore durante la pulizia dei processi mcp-remote orfani: %s", e
        )


def _cleanup_orphaned_mcp_remotes() -> None:
    """Termina i processi mcp-remote orfani rimasti attivi in background da precedenti esecuzioni."""
    import subprocess

    try:
        logger.info("🧹 Rimozione processi mcp-remote orfani...")
        subprocess.run(
            ["pkill", "-f", "mcp-remote"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning(
            "Errore durante la pulizia dei processi mcp-remote orfani: %s", e
        )


@asynccontextmanager
async def _lifespan(app: FastAPI):

    try:
        from src.observability.logging import setup_logging
        from src.observability.hooks_emitter import register_observability_hooks

        setup_logging()
        register_observability_hooks()
        logger.info("Logging and hooks recovered successfully at lifespan startup!")
    except Exception as e:
        logger.error(f"Logging recovery failed at lifespan: {e}", exc_info=True)

    logger.info("Starting application lifespan...")
    _cleanup_orphaned_mcp_remotes()
    try:
        validate_settings_at_startup()
    except Exception as _cfg_err:
        logger.error("Settings validation error: %s", _cfg_err)

    try:
        from src.runtime.redis_client import redis_ping_startup

        await redis_ping_startup()
        logger.info("Redis check done.")
    except Exception as e:
        logger.warning("startup redis: %s", e)

    if os.getenv("AION_UNIFIED_DB", "1").lower() in ("1", "true", "yes"):
        try:
            from src.data.engine import init_engine
            from src.data.bootstrap import ensure_bootstrap_schema
            from src.data.migrations import run_migrations

            eng = init_engine()
            logger.info("DB Engine initialized.")

            # Bootstrap iniziale (tabelle core + FTS5 + trigger + tenant default)
            await ensure_bootstrap_schema(eng)
            logger.info("DB Bootstrap (schema/FTS5/triggers) done.")

            run_migrations()
            logger.info("DB Migrations done.")
            try:
                from src.observability.logging import setup_logging

                setup_logging()
                logger.info(
                    "Logging configuration re-established after Alembic migrations."
                )
            except Exception as log_err:
                logger.warning(
                    "DB migrations done, but failed to restore logging: %s", log_err
                )
            try:
                from src.runtime.timeline_backfill import backfill_message_timelines

                n_tl = await backfill_message_timelines()
                if n_tl:
                    logger.info(
                        "Timeline backfill: updated %d assistant message(s)", n_tl
                    )
            except Exception as tl_exc:  # noqa: BLE001
                logger.warning("Timeline backfill skipped: %s", tl_exc)
            await asyncio.sleep(0.1)

            # Bootstrap admin di default (stile Grafana): garantisce che il
            # pannello /admin sia sempre raggiungibile al primo boot anche
            # se setup_aion_env.py non e' stato eseguito (es. setup
            # automatizzato in container). Idempotente: crea solo se manca.
            try:
                await _bootstrap_default_admin_user()
            except Exception as e:  # noqa: BLE001
                logger.warning("Bootstrap admin default skipped: %s", e)
        except Exception as e:
            logger.error("startup db engine/migrations: %s", e)

    try:
        from src.agent_profile import profile_manager
        from src.runtime.profile_schema import log_validation_report

        report = profile_manager.validate_all()
        log_validation_report(report)
        strict = os.getenv("AION_PROFILE_VALIDATE_STRICT", "0").lower() in (
            "1",
            "true",
            "yes",
        )
        if strict and report.errors:
            raise RuntimeError(
                f"Profile validation failed ({len(report.errors)} error(s)); "
                "fix config/profiles or set AION_PROFILE_VALIDATE_STRICT=0"
            )
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning("profile validation: %s", e)

    try:
        from src.runtime.plugin_loader import load_plugins

        loaded = load_plugins()
        logger.info("Loaded plugins: %s", loaded)
    except Exception as e:
        logger.warning("plugins: %s", e)

    try:
        from src.runtime.hooks import hook_registry
        from src.security.pii_redactor import pii_pre_llm_hook

        hook_registry.register("pre_llm_call", pii_pre_llm_hook, priority=10)
        logger.info("PII hook registered.")
    except Exception as e:
        logger.warning("pii hook: %s", e)

    try:
        from src.runtime.mempalace_warmup import schedule_embedding_warmup

        schedule_embedding_warmup()
        logger.info("MemPalace/Chroma embedding warmup scheduled.")
    except Exception as e:
        logger.warning("mempalace warmup: %s", e)

    try:
        from src.runtime.mcp_startup_warm import (
            startup_warm_async,
            warm_mcp_at_startup,
        )

        if startup_warm_async():
            asyncio.create_task(warm_mcp_at_startup(), name="mcp-startup-warm")
            logger.info("MCP startup warm scheduled (async).")
        else:
            await warm_mcp_at_startup()
    except Exception as e:
        logger.warning("MCP startup warm: %s", e)

    try:
        from src.observability.hooks_emitter import register_observability_hooks

        register_observability_hooks()
        logger.info("Observability hooks registered.")
    except Exception as e:
        logger.warning("observability hooks: %s", e)

    try:
        from src.runtime.cron_scheduler import (
            cron_enabled,
            reload_all_jobs,
            start_scheduler,
        )

        if cron_enabled():
            start_scheduler()
            await reload_all_jobs()
            logger.info("Cron scheduler loaded jobs from DB.")
    except Exception as e:
        logger.warning("cron scheduler: %s", e)

    try:
        from src.mcp_integration_sync import sync_all_mcp_server_configs_from_registry

        result = await sync_all_mcp_server_configs_from_registry()
        logger.info(
            "MCP integration config sync on startup: created=%s updated=%s skipped=%s",
            result.get("created", 0),
            result.get("updated", 0),
            result.get("skipped", 0),
        )
    except Exception as e:
        logger.warning("MCP integration sync on startup failed: %s", e)

    try:
        from src.mcp_integration_sync import sync_all_mcp_server_configs_from_registry

        result = await sync_all_mcp_server_configs_from_registry()
        logger.info(
            "MCP integration config sync on startup: created=%s updated=%s skipped=%s",
            result.get("created", 0),
            result.get("updated", 0),
            result.get("skipped", 0),
        )
    except Exception as e:
        logger.warning("MCP integration sync on startup failed: %s", e)

    logger.info("Application startup sequence complete.")
    yield
    logger.info("Shutting down application...")
    _cleanup_orphaned_mcp_remotes()
    _cleanup_orphaned_mcp_remotes()
    try:
        from src.runtime.cron_scheduler import stop_scheduler

        await stop_scheduler()
    except Exception as e:
        logger.warning("cron scheduler shutdown: %s", e)


# ── Root path per reverse proxy (es. /api quando Caddy strippa il prefisso) ──
_ROOT_PATH = os.getenv("AION_ROOT_PATH", "").rstrip("/")
# ── Docs interattivi API: disabilitati in produzione per sicurezza ──
_API_DOCS = (os.getenv("AION_API_DOCS_ENABLED") or "1").strip().lower() in (
    "1",
    "true",
    "yes",
)

if _ROOT_PATH:
    logger.info(
        "FastAPI root_path set to %r — docs will be at %s/docs", _ROOT_PATH, _ROOT_PATH
    )
if not _API_DOCS:
    logger.info("API interactive docs disabled (AION_API_DOCS_ENABLED=0)")

app = FastAPI(
    title="AION Agent API",
    version=__version__,
    lifespan=_lifespan,
    root_path=_ROOT_PATH,
    docs_url="/docs" if _API_DOCS else None,
    openapi_url="/openapi.json" if _API_DOCS else None,
    redoc_url="/redoc" if _API_DOCS else None,
)

try:
    from src.observability.otel_setup import init_observability

    init_observability(app)
    logger.info("OTel middlewares initialized successfully at module import time!")
except Exception as e:
    logger.error(f"OTel middleware init failed: {e}", exc_info=True)

# --- MIDDLEWARE ---

# 1. CORS — see src/api/cors_config.py (restricted default; wildcard opt-in dev)
from .cors_config import resolve_cors_settings

_cors = resolve_cors_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors.allow_origins,
    allow_origin_regex=_cors.allow_origin_regex,
    allow_credentials=_cors.allow_credentials,
    allow_methods=_cors.allow_methods,
    allow_headers=_cors.allow_headers,
)

# Admin Dashboard Static Files
os.makedirs("static/admin", exist_ok=True)
app.mount(
    "/admin/dashboard",
    StaticFiles(directory="static/admin", html=True),
    name="admin_dashboard",
)

# Include Routers
app.include_router(admin_router)
app.include_router(a2a_router)
app.include_router(session_uploads_router)
app.include_router(api_v1_router)
app.include_router(orchestration_router)
app.include_router(research_router)
app.include_router(plan_execution_router)

from .auth_login import router as auth_login_router
from .chat_ui import router as chat_ui_router

app.include_router(auth_login_router)
app.include_router(chat_ui_router)

# Inclusione ESPLICITA per debug/sicurezza
from .admin_agent_db import router as agent_db_router
from .agent_db_internal import router as agent_db_internal_router

app.include_router(agent_db_router, prefix="/admin/agent-db")
app.include_router(agent_db_internal_router)
logger.info("Agent DB router included directly in main at /admin/agent-db")


@app.middleware("http")
async def _deprecation_headers(request: Request, call_next):
    resp = await call_next(request)
    p = request.url.path
    if p == "/chat" or p.startswith("/sessions/"):
        resp.headers["Deprecation"] = "true"
        resp.headers["Sunset"] = "Wed, 22 Oct 2026 00:00:00 GMT"
        resp.headers["Link"] = '</docs>; rel="successor-version"'
    return resp


@app.post("/chat/stop")
async def chat_stop_compat(
    session_id: str = Query(..., description="conversation / session id"),
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    """Interrompe lo stream agent per sessione (stesso meccanismo di /v1/chat/stop)."""
    await redis_set_stream_cancel(session_id.strip())
    return {"ok": True, "session_id": session_id.strip()}


@app.get("/profiles")
async def profiles_list_compat(
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    """Compat: alcuni client chiamano /profiles invece di /admin/profiles."""
    return await admin_list_profiles()


@app.get("/debug/prompt/{profile_name}")
async def debug_prompt(
    profile_name: str,
    user_id: str = "default",
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    from src.agent_profile import profile_manager

    profile = profile_manager.get_profile(profile_name)
    if not profile:
        return {"error": "Profile not found"}
    return {"prompt": profile.generate_system_prompt(user_id=user_id)}


@app.get("/debug/prompt-snapshots")
async def debug_prompt_snapshots(
    session_id: str = Query(..., description="conversation / session id"),
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    """Full agent prompts captured per turn when AION_PROMPT_DEBUG=1."""
    from src.runtime.prompt_snapshot import list_prompt_snapshots, prompt_debug_enabled

    if not prompt_debug_enabled():
        return {"enabled": False, "snapshots": []}
    sid = session_id.strip()
    return {"enabled": True, "session_id": sid, "snapshots": list_prompt_snapshots(sid)}


# --- Models ---
class AttachmentRef(BaseModel):
    """Riferimento a un file già caricato via POST .../upload nella stessa sessione."""

    relative_path: str
    original_name: Optional[str] = None
    mime: Optional[str] = None


ReasoningEffort = Literal["min", "medium", "max"]
MessageSource = Literal["user_input", "internal_trigger", "scheduled_trigger"]


class ChatRequest(BaseModel):
    message: str
    session_id: str
    profile: str = Field(
        default="generic_assistant",
        validation_alias=AliasChoices("profile", "profile_name"),
    )
    user_id: Optional[str] = None
    attachments: Optional[List[AttachmentRef]] = None
    turn_attachments: Optional[List[AttachmentRef]] = None
    reasoning_effort: Optional[ReasoningEffort] = Field(
        default=None,
        description="Omit per usare AION_DEFAULT_REASONING_EFFORT / AION_THINKING_ENABLED. min=off, medium=default generatore, max=thinking+budget opzionale.",
    )
    thinking_enabled: Optional[bool] = None
    user_message_id: Optional[str] = None
    assistant_message_id: Optional[str] = None
    message_source: MessageSource = Field(
        default="user_input",
        description="Origine del messaggio: input utente reale o trigger interno di orchestrazione.",
    )
    web_search_enabled: Optional[bool] = None
    web_search_restrict_hosts: Optional[List[str]] = None
    agent_mode: Optional[str] = "normal"
    plan_mode: Optional[bool] = None
    deep_research_mode: Optional[bool] = None
    sql_query_project: Optional[str] = Field(
        default=None,
        description="Slug cassetto QueryMemory SQL per questa conversazione.",
    )


# --- Globals ---
_GLOBAL_LOOP = None


@app.post("/chat")
async def chat(
    request: ChatRequest,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    logger.info(">>> API: Received chat request for session %s", request.session_id)
    global _GLOBAL_LOOP
    _GLOBAL_LOOP = asyncio.get_running_loop()

    # Quando la password auth e' attiva, l'identita' canonica viene
    # dall'authenticated user (override del X-AION-User-Id arbitrario).
    if auth.via == "chat_token" and auth.identifier:
        user_id = sanitize_user_id(auth.identifier)
    else:
        user_id = sanitize_user_id(x_aion_user_id or request.user_id)

    from src.runtime.agent_mode_resolve import resolve_agent_mode

    resolved_agent_mode = resolve_agent_mode(
        request.agent_mode,
        request.plan_mode,
        deep_research_mode=request.deep_research_mode,
        message_source=request.message_source,
    )

    sql_project_resolved = (request.sql_query_project or "").strip() or None
    conversation_project: str | None = None

    try:
        from opentelemetry import trace

        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.set_attribute("aion.session_id", request.session_id or "")
            current_span.set_attribute("aion.user_id", user_id or "")
            current_span.set_attribute("aion.profile", request.profile or "")
            current_span.set_attribute("aion.tenant_id", "default")
            current_span.set_attribute("aion.user_question", request.message or "")
    except Exception as e:
        logger.warning("Failed to set trace attributes in chat endpoint: %s", e)

    if os.getenv("AION_UNIFIED_DB", "1").lower() in ("1", "true", "yes"):
        try:
            from datetime import datetime, timezone
            from src.data.engine import get_async_session_maker
            from src.data.models import Conversation

            async with get_async_session_maker()() as session:
                r = await session.get(Conversation, request.session_id)
                if not r:
                    meta = {}
                    if request.thinking_enabled is not None:
                        meta["thinking_enabled"] = request.thinking_enabled
                    if request.reasoning_effort is not None:
                        meta["reasoning_effort"] = request.reasoning_effort
                    meta["agent_mode"] = resolved_agent_mode
                    if request.plan_mode is not None:
                        meta["plan_mode"] = request.plan_mode
                    if request.deep_research_mode is not None:
                        meta["deep_research_mode"] = request.deep_research_mode
                    if request.sql_query_project is not None:
                        meta["sql_query_project"] = request.sql_query_project

                    tenant = (
                        os.getenv("AION_DEFAULT_TENANT_ID") or "default"
                    ).strip() or "default"
                    r = Conversation(
                        id=request.session_id,
                        tenant_id=tenant,
                        user_id=user_id,
                        profile_slug=request.profile,
                        title=None,
                        message_count=0,
                        metadata_json=json.dumps(meta),
                    )
                    session.add(r)
                    await session.commit()
                else:
                    meta = json.loads(r.metadata_json or "{}")
                    updated = False
                    if r.profile_slug != request.profile:
                        r.profile_slug = request.profile
                        updated = True
                    if (
                        request.thinking_enabled is not None
                        and meta.get("thinking_enabled") != request.thinking_enabled
                    ):
                        meta["thinking_enabled"] = request.thinking_enabled
                        updated = True
                    if (
                        request.reasoning_effort is not None
                        and meta.get("reasoning_effort") != request.reasoning_effort
                    ):
                        meta["reasoning_effort"] = request.reasoning_effort
                        updated = True
                    if meta.get("agent_mode") != resolved_agent_mode:
                        meta["agent_mode"] = resolved_agent_mode
                        updated = True
                    if (
                        request.plan_mode is not None
                        and meta.get("plan_mode") != request.plan_mode
                    ):
                        meta["plan_mode"] = request.plan_mode
                        updated = True
                    if (
                        request.sql_query_project is not None
                        and meta.get("sql_query_project") != request.sql_query_project
                    ):
                        meta["sql_query_project"] = request.sql_query_project
                        updated = True
                    if updated:
                        r.metadata_json = json.dumps(meta)
                        r.updated_at = datetime.now(timezone.utc)
                        session.add(r)
                        await session.commit()
                    conversation_project = (
                        meta.get("sql_query_project") or ""
                    ).strip() or None
        except Exception as e:
            logger.error("Error ensuring/updating conversation metadata in chat: %s", e)

    from src.runtime.sql_query_project_resolve import resolve_sql_query_project

    sql_project_resolved = resolve_sql_query_project(
        request_project=request.sql_query_project,
        conversation_project=conversation_project,
    )
    if sql_project_resolved:
        logger.info(
            "chat sql_query_project resolved=%s request=%s conversation=%s session=%s",
            sql_project_resolved,
            request.sql_query_project,
            conversation_project,
            request.session_id[:12],
        )

    _tenant_qm = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    _project_access_err: str | None = None
    try:
        from src.runtime.query_memory_hooks import profile_has_memory_capability_by_slug
        from src.runtime.sql_query_project_scope import verify_user_project_access

        if sql_project_resolved and profile_has_memory_capability_by_slug(
            request.profile
        ):
            _project_access_err = await verify_user_project_access(
                project_slug=sql_project_resolved,
                tenant_id=_tenant_qm,
                user_id=user_id,
                profile_slug=request.profile,
            )
    except Exception as access_exc:
        logger.warning("sql project access check skipped: %s", access_exc)

    att = None
    if request.attachments:
        att = [a.model_dump() for a in request.attachments]

    turn_att = None
    if request.turn_attachments:
        turn_att = [a.model_dump() for a in request.turn_attachments]

    async def event_generator():
        logger.info(">>> API: event_generator STARTED")
        yield {"comment": "aion-open"}
        if _project_access_err:
            yield {"event": "error", "data": json.dumps({"error": _project_access_err})}
            return
        try:
            logger.info(
                ">>> API: Getting agent instance for profile %s with mode %s...",
                request.profile,
                resolved_agent_mode,
            )
            agent_instance, profile_name = await get_agent(
                request.profile,
                session_id=request.session_id,
                user_id=user_id,
                agent_mode=resolved_agent_mode,
                message_source=request.message_source,
            )
            logger.info(">>> API: Agent instance ready (%s)", profile_name)
            pipeline = AgentPipeline(
                agent=agent_instance,
                session_id=request.session_id,
                profile_name=profile_name,
                user_id=user_id,
                agent_mode=resolved_agent_mode,
            )
            if request.thinking_enabled is False:
                resolved_effort = "min"
            else:
                resolved_effort = effective_reasoning_effort(request.reasoning_effort)
            async for chunk in pipeline.run_stream(
                request.message,
                attachments=att,
                turn_attachments=turn_att,
                reasoning_effort=resolved_effort,
                user_message_id=request.user_message_id,
                assistant_message_id=request.assistant_message_id,
                message_source=request.message_source,
                web_search_enabled=request.web_search_enabled,
                web_search_restrict_hosts=normalize_web_search_restrict_hosts(
                    request.web_search_restrict_hosts
                ),
                sql_query_project=sql_project_resolved,
            ):
                yield {"event": "message", "data": json.dumps(chunk)}
        except Exception as e:
            from src.agent_profile import ProfileNotFoundError

            logger.error(">>> API: ERROR in event_generator: %s", e, exc_info=True)
            if isinstance(e, ProfileNotFoundError):
                payload = {
                    "error": str(e),
                    "code": "profile_not_found",
                    "available_slugs": e.available_slugs,
                }
            else:
                payload = {"error": str(e)}
            yield {"event": "error", "data": json.dumps(payload)}
        logger.info(">>> API: event_generator FINISHED")

    return EventSourceResponse(
        event_generator(),
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/sessions/{session_id}/charts")
async def get_session_charts(
    session_id: str,
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    """
    Chart accumulati nel turno (stesso processo) per la sessione chat-ui.
    Consuma la coda: una GET restituisce e svuota i grafici pendenti.
    """
    charts = chart_queue.get_serialized(session_id)
    return {"charts": charts}


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "aion-api"}


def _uvicorn_reload_exclude_paths() -> list[str]:
    """
    Esclude dal file-watcher di uvicorn (--reload) i .py sotto le cartelle sessione
    (es. workspace/_sandbox_last_run.py scritto dal tool MCP), altrimenti ogni esecuzione
    sandbox riavvia il server.
    """
    from src.session_workspace import data_root

    sessions = data_root() / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    return [str(sessions.resolve())]


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("AION_API_HOST", "0.0.0.0")
    port = int(os.getenv("AION_API_PORT", "8001"))
    use_reload = os.getenv("AION_API_RELOAD", "0").lower() in ("1", "true", "yes")
    # ``asyncio`` evita uvloop: con SIGINT (Ctrl+C) durante richieste lunghe, uvloop può loggare
    # ``RuntimeError: this event loop is already running`` in fase di shutdown del Runner.
    _loop = (os.getenv("AION_API_LOOP") or "auto").strip().lower()
    if _loop not in ("auto", "asyncio", "uvloop"):
        _loop = "auto"
    _grace = os.getenv("AION_API_GRACEFUL_SHUTDOWN_SEC", "8").strip()
    try:
        timeout_graceful_shutdown = max(1, int(_grace))
    except ValueError:
        timeout_graceful_shutdown = 8
    _uvicorn_kw = dict(
        host=host,
        port=port,
        loop=_loop,
        timeout_graceful_shutdown=timeout_graceful_shutdown,
    )

    if use_reload:
        uvicorn.run(
            "src.api.main:app",
            reload=True,
            reload_excludes=_uvicorn_reload_exclude_paths(),
            **_uvicorn_kw,
        )
    else:
        uvicorn.run(app, **_uvicorn_kw)
