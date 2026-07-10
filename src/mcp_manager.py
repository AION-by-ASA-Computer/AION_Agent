import copy
import os
import shutil
import sys
import time
import yaml
import asyncio
import logging
import atexit
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from contextlib import asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

from .config import resolve_env_placeholders
from .mcp_connector_catalog import apply_runtime_env_aliases

from .identity import sanitize_user_id
from .session_workspace import data_root
from .security.container_runtime import sandbox_container_mode_enabled
from .runtime.mempalace_warmup import apply_shared_embedding_cache_env
from .khub_auth import khub_token_manager
from .mcp_registry_io import companion_json_path, load_registry_file
from src.observability import metrics

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    """Root del repository (indipendente da ``os.getcwd()``)."""
    return Path(__file__).resolve().parent.parent


def _resolved_mcp_registry_path() -> str:
    """Percorso assoluto del registry base MCP (``AION_MCP_REGISTRY_PATH`` opzionale)."""
    explicit = os.getenv("AION_MCP_REGISTRY_PATH")
    root = _repo_root()
    if explicit:
        p = Path(explicit)
        return str(p if p.is_absolute() else (root / p))
    return str(root / "config" / "mcp_registry.yaml")


REGISTRY_PATH = _resolved_mcp_registry_path()


# Pool MCP stdio persistente: default on via settings (P2.7).
def _pool_enabled() -> bool:
    try:
        from .settings import get_settings

        return bool(get_settings().mcp_pool)
    except Exception:
        return os.getenv("AION_MCP_POOL", "1").lower() not in ("0", "false", "no")


_USE_POOL = _pool_enabled()

# Sessione sintetica per warm al boot API e contesto spawn worker user-pool.
BOOTSTRAP_SESSION_ID = "__bootstrap__"


def _parse_user_pool_key(pool_key: str) -> Optional[Tuple[str, str]]:
    """Estrae (user_id, tenant_id) da chiavi pool ``__user__{uid}__{tid}``."""
    prefix = "__user__"
    if not pool_key.startswith(prefix):
        return None
    rest = pool_key[len(prefix) :]
    if "__" not in rest:
        return None
    uid, tid = rest.rsplit("__", 1)
    if not uid:
        return None
    return uid, (tid or "default").strip() or "default"


# Server che leggono AION_CHAT_SESSION_ID a runtime: un worker per chat session.
_DEFAULT_SESSION_SCOPED_SERVERS = frozenset(
    {
        "session_sandbox",
        "promo_render",
        "ocr",  # registry slug in config/mcp_registry.yaml (folder: ocr_mcp/)
        "ocr_mcp",  # legacy alias
        "skills_hub",
        "memory",
        "aion_subagents",
    }
)


def _user_pool_enabled() -> bool:
    try:
        from .settings import get_settings

        return bool(get_settings().mcp_user_pool)
    except Exception:
        return os.getenv("AION_MCP_USER_POOL", "1").lower() not in ("0", "false", "no")


def _session_scoped_servers() -> frozenset[str]:
    try:
        from .settings import get_settings

        raw = (get_settings().mcp_session_scoped_servers or "").strip()
    except Exception:
        raw = (os.getenv("AION_MCP_SESSION_SCOPED_SERVERS") or "").strip()
    if raw:
        configured = frozenset(s.strip() for s in raw.split(",") if s.strip())
        # Always keep built-in session-scoped servers (registry slug `ocr` vs folder `ocr_mcp/`, etc.).
        return _DEFAULT_SESSION_SCOPED_SERVERS | configured
    return _DEFAULT_SESSION_SCOPED_SERVERS


def _session_env_inject_enabled() -> bool:
    try:
        from .settings import get_settings

        return bool(get_settings().mcp_session_env_inject)
    except Exception:
        return os.getenv("AION_MCP_SESSION_ENV_INJECT", "0").lower() not in (
            "0",
            "false",
            "no",
        )


def _apply_call_session_env(
    chat_session_id: str, ctx: Optional[Tuple[str, ...]]
) -> Dict[str, Optional[str]]:
    """Sovrascrive env nel sottoprocesso MCP per una singola call_tool (user-pool)."""
    backup: Dict[str, Optional[str]] = {}
    if chat_session_id:
        backup["AION_CHAT_SESSION_ID"] = os.environ.get("AION_CHAT_SESSION_ID")
        os.environ["AION_CHAT_SESSION_ID"] = chat_session_id
    if ctx:
        if len(ctx) == 2:
            slug, uid = ctx
            tid = "default"
        else:
            slug, uid, tid = ctx
        for key, val in (
            ("AION_CURRENT_PROFILE_SLUG", slug),
            ("AION_CURRENT_USER_ID", uid),
            ("AION_CURRENT_TENANT_ID", tid or "default"),
        ):
            backup[key] = os.environ.get(key)
            os.environ[key] = str(val)
        from .agent_profile import profile_manager

        profile = profile_manager.get_profile(slug)
        if profile and getattr(profile, "wren_project_path", None):
            backup["AION_WREN_PROJECT_PATH"] = os.environ.get("AION_WREN_PROJECT_PATH")
            os.environ["AION_WREN_PROJECT_PATH"] = profile.wren_project_path
    return backup


def _restore_call_session_env(backup: Dict[str, Optional[str]]) -> None:
    for key, val in backup.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


def _default_local_registry_path(base_path: str) -> str:
    explicit = os.getenv("AION_MCP_REGISTRY_LOCAL_PATH")
    if explicit:
        p = Path(explicit)
        return str(p if p.is_absolute() else (_repo_root() / p))
    d, f = os.path.split(base_path)
    stem, ext = os.path.splitext(f)
    return os.path.join(d or str(_repo_root()), f"{stem}.local{ext}")


def _maybe_migrate_local_registry(local_path: str) -> None:
    """Copia overlay legacy da config/ al path dati se Docker monta config :ro."""
    target = Path(local_path)
    if target.is_file():
        return
    legacy = _repo_root() / "config" / "mcp_registry.local.yaml"
    if not legacy.is_file() or legacy.resolve() == target.resolve():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
        logger.info("Migrated local MCP registry %s -> %s", legacy, target)
    except OSError as ex:
        logger.warning("Could not migrate local MCP registry: %s", ex)


def _merge_mcp_registries(
    base: Dict[str, Any], local: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Merge: chiavi in `local` sovrascrivono `base`.
    `local['_removed']` è una lista di nomi server da escludere dal base (disinstallazione soft).
    """
    base = base or {}
    local = local or {}
    removed = set(local.get("_removed") or [])
    out = {k: copy.deepcopy(v) for k, v in base.items() if k not in removed}
    for k, v in local.items():
        if k == "_removed":
            continue
        out[k] = copy.deepcopy(v)
    return out


def _apply_mcp_home_isolation(env: Dict[str, Any], uid: str) -> None:
    """Isola HOME/XDG per processo MCP (per user_id)."""
    if os.getenv("AION_MCP_USER_HOME_ISOLATION", "1").lower() not in (
        "1",
        "true",
        "yes",
    ):
        return
    safe_uid = sanitize_user_id(uid)
    user_mcp_home = data_root() / "users" / safe_uid / "mcp_home"
    user_mcp_home.mkdir(parents=True, exist_ok=True)
    for xdg_sub in (".config", ".local/share", ".cache"):
        (user_mcp_home / xdg_sub).mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(user_mcp_home)
    env["XDG_CONFIG_HOME"] = str(user_mcp_home / ".config")
    env["XDG_DATA_HOME"] = str(user_mcp_home / ".local" / "share")
    env["XDG_CACHE_HOME"] = str(user_mcp_home / ".cache")
    env["USERPROFILE"] = str(user_mcp_home)
    env["APPDATA"] = str(user_mcp_home / ".config")
    logger.debug("MCP HOME isolation: user=%s home=%s", uid, user_mcp_home)


def _adjust_stdio_spawn_env(process_env: Dict[str, Any], command: str) -> None:
    """Evita che la venv del backend interferisca con ``uv run`` / ``uvx`` nei sottoprocessi MCP."""
    base = os.path.basename(str(command or "")).lower()
    if base in ("uv", "uvx"):
        process_env.pop("VIRTUAL_ENV", None)


def normalize_mcp_email_server_env(env: Dict[str, Any]) -> Dict[str, Any]:
    """Allinea nomi env al pacchetto mcp-email-server (IMAP_SSL, SMTP_START_SSL, …)."""
    if not env:
        return env
    e = dict(env)
    if (
        not str(e.get("MCP_EMAIL_SERVER_IMAP_SSL") or "").strip()
        and str(e.get("MCP_EMAIL_SERVER_IMAP_VERIFY_SSL") or "").strip()
    ):
        e["MCP_EMAIL_SERVER_IMAP_SSL"] = e["MCP_EMAIL_SERVER_IMAP_VERIFY_SSL"]
    if (
        not str(e.get("MCP_EMAIL_SERVER_SMTP_SSL") or "").strip()
        and str(e.get("MCP_EMAIL_SERVER_SMTP_VERIFY_SSL") or "").strip()
    ):
        e["MCP_EMAIL_SERVER_SMTP_SSL"] = e["MCP_EMAIL_SERVER_SMTP_VERIFY_SSL"]
    try:
        smtp_port = int(
            str(e.get("MCP_EMAIL_SERVER_SMTP_PORT", "465")).strip() or "465"
        )
    except ValueError:
        smtp_port = 465
    if smtp_port == 587:
        if not str(e.get("MCP_EMAIL_SERVER_SMTP_START_SSL") or "").strip():
            e["MCP_EMAIL_SERVER_SMTP_START_SSL"] = "true"
        if not str(e.get("MCP_EMAIL_SERVER_SMTP_SSL") or "").strip():
            e["MCP_EMAIL_SERVER_SMTP_SSL"] = "false"
    return e


def sanitize_mcp_tool_arguments(arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Rimuove chiavi con valori '' / 'None' / 'null' / None per evitare errori di validazione (es. in Zod con campi optional non nullable)."""
    out: Dict[str, Any] = {}
    for k, v in (arguments or {}).items():
        if v is None:
            continue
        if isinstance(v, str):
            s = v.strip()
            if s in ("", "None", "null", "NULL"):
                continue
        out[k] = v
    return out


def _merge_mcp_subprocess_env(
    process_env: Dict[str, Any], server_env: Optional[Dict[str, Any]]
) -> None:
    """
    Unisce ``server_env`` (dal registry, già risolto con resolve_env_placeholders) nell'env del sottoprocesso.

    Non sovrascrive con stringhe vuote: così un placeholder non risolto in YAML non cancella la stessa
    variabile già presente in ``os.environ`` (tipico token solo in ``.env``).
    """
    if not server_env:
        return
    for k, v in server_env.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        process_env[k] = v


class MCPStdioWorker:
    """
    Un processo stdio MCP e una ClientSession gestiti in un unico task asyncio.
    Tutte le operazioni (list_tools / call_tool) passano in coda e serializzano l'accesso.
    """

    def __init__(
        self,
        manager: "MCPManager",
        server_name: str,
        chat_session_id: str,
        *,
        pool_user_id: Optional[str] = None,
        pool_tenant_id: Optional[str] = None,
    ):
        self._manager = manager
        self.server_name = server_name
        self._chat_session_id = chat_session_id
        self._pool_user_id = (pool_user_id or "").strip() or None
        self._pool_tenant_id = (pool_tenant_id or "").strip() or None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._start_lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._init_error: Optional[BaseException] = None
        self.last_access = asyncio.get_event_loop().time()
        self._is_active = False
        self._container_jail = False

    def _pool_scope_id(self) -> str:
        sid = (self._chat_session_id or BOOTSTRAP_SESSION_ID).strip()
        return self._manager._resolve_pool_key(sid, self.server_name)[0]

    async def start(self) -> None:
        async with self._start_lock:
            if self._task is not None and not self._task.done():
                await self._wait_ready()
                return
            pool_sid = self._pool_scope_id()
            if self._init_error is not None and self._manager._warm_circuit_open(
                pool_sid, self.server_name
            ):
                return
            # Riavvio dopo crash o completamento del task precedente
            self._task = None
            self._ready.clear()
            self._init_error = None
            self._task = asyncio.create_task(
                self._run(), name=f"mcp-stdio-{self.server_name}"
            )
            await self._wait_ready()

    async def _wait_ready(self) -> None:
        await self._ready.wait()
        if self._init_error is not None:
            raise self._init_error

    async def _run(self) -> None:
        try:
            config = self._manager.get_server_config(self.server_name)
            if not config:
                raise ValueError(
                    f"MCP server '{self.server_name}' not found in registry"
                )
            command = config.get("command", "python")
            if command == "python":
                command = self._manager.get_python_exe(self.server_name)
            elif isinstance(command, str) and (
                "/" in command or os.path.sep in command
            ):
                cmd_path = Path(command)
                if not cmd_path.is_absolute():
                    cand = _repo_root() / command
                    if cand.is_file():
                        command = str(cand.resolve())
            args = self._manager.resolve_stdio_args(list(config.get("args", [])))
            env = os.environ.copy()
            project_root = os.getcwd()
            env.setdefault("FASTMCP_LOG_LEVEL", "ERROR")
            env.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")
            env.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")
            env.setdefault("NO_COLOR", "1")
            env.setdefault("TQDM_DISABLE", "1")
            env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            env["PYTHONPATH"] = f"{project_root}:{env.get('PYTHONPATH', '')}"
            lookup_sid = self._chat_session_id or BOOTSTRAP_SESSION_ID
            env["AION_CHAT_SESSION_ID"] = self._chat_session_id or ""
            if self._pool_user_id:
                uid = self._pool_user_id
                tid = self._pool_tenant_id or "default"
                bootstrap_ctx = self._manager._session_ctx.get(lookup_sid)
                if bootstrap_ctx:
                    if len(bootstrap_ctx) == 2:
                        slug, _ = bootstrap_ctx
                    else:
                        slug, _, _ = bootstrap_ctx
                else:
                    slug = "generic_assistant"
            else:
                ctx = self._manager._session_ctx.get(
                    lookup_sid, ("generic_assistant", "default", "default")
                )
                if len(ctx) == 2:
                    slug, uid = ctx
                    tid = "default"
                else:
                    slug, uid, tid = ctx
            env["AION_CURRENT_PROFILE_SLUG"] = slug
            env["AION_CURRENT_USER_ID"] = uid
            env["AION_CURRENT_TENANT_ID"] = tid
            from .agent_profile import profile_manager

            profile = profile_manager.get_profile(slug)
            if profile and getattr(profile, "wren_project_path", None):
                env["AION_WREN_PROJECT_PATH"] = profile.wren_project_path

            if config.get("remote_url"):
                env["MCP_REMOTE_URL"] = config["remote_url"]

            _apply_mcp_home_isolation(env, uid)
            if self.server_name == "mempalace":
                apply_shared_embedding_cache_env(env)
                from .memory.project_memory_scope import apply_mempalace_palace_env

                apply_mempalace_palace_env(env, tid)
            if "env" in config:
                from .runtime.credential_store import resolve_mcp_env_for_user

                resolved_server_env = await resolve_mcp_env_for_user(
                    config.get("env"),
                    user_id=sanitize_user_id(uid),
                    tenant_id=tid,
                    server_slug=self.server_name,
                )
                if (
                    self.server_name == "mcp-email-server"
                    or "email" in self.server_name
                ):
                    resolved_server_env = normalize_mcp_email_server_env(
                        resolved_server_env
                    )
                _merge_mcp_subprocess_env(env, resolved_server_env)
            apply_runtime_env_aliases(env, self.server_name, config)
            _adjust_stdio_spawn_env(env, command)

            if (
                self.server_name == "session_sandbox"
                and not sandbox_container_mode_enabled()
            ):
                from .security.session_env import scrub_secrets_from_env

                scrub_secrets_from_env(env)

            if (
                self.server_name == "session_sandbox"
                and sandbox_container_mode_enabled()
            ):
                from .security.container_runtime import get_container_runtime
                from .security.session_runner import (
                    SandboxBackendUnavailable,
                    fail_closed,
                )

                runtime = get_container_runtime()
                if not runtime.is_available():
                    msg = (
                        "Session sandbox container runtime unavailable "
                        f"({runtime.runtime}); set AION_SANDBOX_BACKEND=subprocess for dev"
                    )
                    if fail_closed():
                        self._init_error = SandboxBackendUnavailable(msg)
                        self._ready.set()
                        return
                    logger.warning("%s — falling back to host subprocess", msg)
                else:
                    sid = (self._chat_session_id or "").strip()
                    if not sid:
                        self._init_error = RuntimeError(
                            "session_sandbox container mode requires AION_CHAT_SESSION_ID"
                        )
                        self._ready.set()
                        return
                    command, args, env = runtime.build_stdio_spawn(
                        sid,
                        profile_slug=slug,
                        user_id=uid,
                        tenant_id=tid,
                    )
                    self._container_jail = True

            server_params = StdioServerParameters(command=command, args=args, env=env)

            logger.info(
                "🔌 MCP pool: avvio persistente stdio per '%s'", self.server_name
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    try:
                        # Handshake con timeout per evitare blocchi infiniti se il server è appeso
                        init_timeout = float(os.getenv("AION_MCP_INIT_TIMEOUT", "60"))
                        await asyncio.wait_for(
                            session.initialize(), timeout=init_timeout
                        )
                        self._init_error = None
                        self._ready.set()
                        logger.info(
                            "✅ MCP '%s' inizializzato con successo", self.server_name
                        )
                        await self._manager._increment_active_server(self.server_name)
                        self._is_active = True
                    except asyncio.TimeoutError:
                        logger.error(
                            "❌ Handshake TIMEOUT per '%s' dopo %ss",
                            self.server_name,
                            int(init_timeout),
                        )
                        self._init_error = asyncio.TimeoutError(
                            f"Server {self.server_name} initialization timed out"
                        )
                        self._ready.set()
                        return
                    except Exception as e:
                        logger.error(
                            "❌ Errore durante inizializzazione MCP '%s': %s",
                            self.server_name,
                            e,
                        )
                        self._init_error = e
                        self._ready.set()
                        return

                    while True:
                        op = await self._queue.get()
                        if op is None:
                            break
                        kind, fut, payload = op
                        try:
                            if kind == "list_tools":
                                res = await session.list_tools()
                                if not fut.cancelled():
                                    fut.set_result(res)
                            elif kind == "call_tool":
                                from .runtime.pg_query_guard import (
                                    postgres_query_timeout_sec,
                                )

                                raw_args = payload.get("arguments") or {}
                                tool_name = payload.get("name") or ""
                                inject_sid = (
                                    payload.get("chat_session_id")
                                    or self._chat_session_id
                                    or ""
                                ).strip()
                                env_backup: Dict[str, Optional[str]] = {}
                                if _session_env_inject_enabled() and inject_sid:
                                    ctx = self._manager._session_ctx.get(inject_sid)
                                    env_backup = _apply_call_session_env(
                                        inject_sid, ctx
                                    )
                                try:
                                    if self.server_name == "mempalace":
                                        from .runtime.mempalace_tool_scope import (
                                            apply_mempalace_project_scope,
                                            mempalace_write_blocked_message,
                                        )

                                        blocked = mempalace_write_blocked_message(
                                            tool_name
                                        )
                                        if blocked:
                                            if not fut.cancelled():
                                                fut.set_exception(RuntimeError(blocked))
                                            continue
                                        raw_args = apply_mempalace_project_scope(
                                            tool_name, raw_args
                                        )
                                    call_coro = session.call_tool(
                                        name=tool_name,
                                        arguments=sanitize_mcp_tool_arguments(raw_args),
                                    )
                                    q_timeout = postgres_query_timeout_sec(
                                        self.server_name, tool_name
                                    )
                                    if q_timeout:
                                        res = await asyncio.wait_for(
                                            call_coro, timeout=q_timeout
                                        )
                                    else:
                                        res = await call_coro
                                    if not fut.cancelled():
                                        fut.set_result(res)
                                finally:
                                    if env_backup:
                                        _restore_call_session_env(env_backup)
                            self.last_access = asyncio.get_event_loop().time()
                        except asyncio.TimeoutError:
                            from .runtime.pg_query_guard import (
                                postgres_query_timeout_sec,
                            )

                            cap = postgres_query_timeout_sec(
                                self.server_name, payload.get("name") or ""
                            )
                            err = TimeoutError(
                                f"PostgreSQL query exceeded {cap}s "
                                f"({self.server_name}/{payload.get('name')})"
                            )
                            if not fut.done():
                                fut.set_exception(err)
                            logger.error(
                                "MCP worker '%s' query timeout — recycling stdio process",
                                self.server_name,
                            )
                            if self._task and not self._task.done():
                                self._task.cancel()
                            break
                        except Exception as e:
                            if not fut.done():
                                fut.set_exception(e)
        except Exception as e:
            self._init_error = e
            logger.error(
                "MCP worker '%s' terminato con errore: %s", self.server_name, e
            )
            self._ready.set()
        finally:
            if self._is_active:
                await self._manager._decrement_active_server(self.server_name)
                self._is_active = False
            else:
                metrics.aion_mcp_server_healthy.labels(mcp_server=self.server_name).set(
                    0
                )
            if not self._ready.is_set():
                self._ready.set()

    async def list_tools(self):
        await self.start()
        if self._init_error is not None:
            raise self._init_error
        if self._task is None or self._task.done():
            raise RuntimeError(f"MCP server '{self.server_name}' unavailable")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        await self._queue.put(("list_tools", fut, None))
        return await fut

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        chat_session_id: Optional[str] = None,
    ):
        logger.debug("mcp_worker_call_tool server=%s tool=%s", self.server_name, name)
        await self.start()
        if self._init_error is not None:
            raise self._init_error
        if self._task is None or self._task.done():
            raise RuntimeError(f"MCP server '{self.server_name}' unavailable")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        sid = (chat_session_id or self._chat_session_id or "").strip()
        await self._queue.put(
            (
                "call_tool",
                fut,
                {"name": name, "arguments": arguments, "chat_session_id": sid},
            )
        )
        return await fut

    async def shutdown(self) -> None:
        sid = (self._chat_session_id or "").strip()
        if self._container_jail and sid:
            try:
                from .security.container_runtime import get_container_runtime

                await get_container_runtime().stop_session_container(sid)
            except Exception as exc:
                logger.warning(
                    "MCP worker '%s' container stop failed: %s",
                    self.server_name,
                    exc,
                )
        if self._task and not self._task.done():
            await self._queue.put(None)
            try:
                await asyncio.wait_for(
                    self._task,
                    timeout=float(os.getenv("AION_MCP_WORKER_SHUTDOWN_TIMEOUT", "15")),
                )
            except asyncio.TimeoutError:
                self._task.cancel()
        self._task = None
        self._container_jail = False


class MCPManager:
    """
    Registry MCP + pool di sessioni stdio persistenti per (chat_session_id, server_name).

    - `registry_path`: YAML di progetto (commitabile), es. config/mcp_registry.yaml
    - `local_registry_path`: overlay utente (gitignored), merge sopra il base
    """

    def __init__(
        self,
        registry_path: str = REGISTRY_PATH,
        local_registry_path: Optional[str] = None,
    ):
        self.registry_path = registry_path
        self.local_registry_path = local_registry_path or _default_local_registry_path(
            registry_path
        )
        self._registry_base: Dict[str, Any] = {}
        self._registry_local: Dict[str, Any] = {}
        self._registry: Dict[str, Any] = {}
        self._pool: Dict[Tuple[str, str], MCPStdioWorker] = {}
        self._pool_lock = asyncio.Lock()
        # session_id -> (profile_slug, user_id, tenant_id) per env MCP e injection agent_db
        self._session_ctx: Dict[str, Tuple[str, str, str]] = {}
        self._active_servers: Dict[str, int] = {}
        self._active_servers_lock = asyncio.Lock()
        # (pool_scope_id, server_name) -> (monotonic_fail_time, error_message)
        self._warm_failures: Dict[Tuple[str, str], Tuple[float, str]] = {}
        self._warm_locks: Dict[Tuple[str, str], asyncio.Lock] = {}
        self._registry_load_mtimes: Tuple[float, float] = (0.0, 0.0)
        self._health_labels_initialized: set = set()
        self.load_registry()
        self._cleanup_task: Optional[asyncio.Task] = None
        atexit.register(self._atexit_sync)

    def _warm_fail_cooldown_sec(self) -> float:
        try:
            return max(30.0, float(os.getenv("AION_MCP_WARM_FAIL_COOLDOWN_SEC", "600")))
        except ValueError:
            return 600.0

    def _warm_timeout_sec(self, *, retry: bool) -> float:
        key = (
            "AION_MCP_WARM_RETRY_TIMEOUT_SEC" if retry else "AION_MCP_WARM_TIMEOUT_SEC"
        )
        default = "3" if retry else "10"
        try:
            return max(1.0, float(os.getenv(key, default)))
        except ValueError:
            return 3.0 if retry else 10.0

    def _warm_circuit_open(self, pool_scope_id: str, server_name: str) -> bool:
        rec = self._warm_failures.get((pool_scope_id, server_name))
        if not rec:
            return False
        fail_time, _msg = rec
        return (time.monotonic() - fail_time) < self._warm_fail_cooldown_sec()

    def _warm_failure_message(self, pool_scope_id: str, server_name: str) -> str:
        rec = self._warm_failures.get((pool_scope_id, server_name))
        if rec:
            return rec[1]
        return "MCP warm skipped (recent failure)"

    def _record_warm_failure(
        self, pool_scope_id: str, server_name: str, error: str
    ) -> None:
        self._warm_failures[(pool_scope_id, server_name)] = (
            time.monotonic(),
            (error or "unknown error")[:2000],
        )

    def _clear_warm_failure(self, pool_scope_id: str, server_name: str) -> None:
        self._warm_failures.pop((pool_scope_id, server_name), None)

    def _is_server_healthy(self, chat_session_id: str, server_name: str) -> bool:
        if not self._is_stdio_server(server_name):
            return True
        key = self._resolve_pool_key(chat_session_id, server_name)
        worker = self._pool.get(key)
        if worker is None:
            return False
        if worker._task is None or worker._task.done():
            return False
        if worker._init_error is not None:
            return False
        return worker._ready.is_set()

    def _warm_lock(self, pool_scope_id: str, server_name: str) -> asyncio.Lock:
        key = (pool_scope_id, server_name)
        lock = self._warm_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._warm_locks[key] = lock
        return lock

    # Funzione per incrementare il numero di sessioni attive e settare la metrica di health del server MCP
    async def _increment_active_server(self, name: str) -> None:
        async with self._active_servers_lock:
            self._active_servers[name] = self._active_servers.get(name, 0) + 1
            metrics.aion_mcp_server_healthy.labels(mcp_server=name).set(1)

    async def _decrement_active_server(self, name: str) -> None:
        async with self._active_servers_lock:
            current = self._active_servers.get(name, 0)
            if current > 0:
                self._active_servers[name] = current - 1
                if self._active_servers[name] == 0:
                    metrics.aion_mcp_server_healthy.labels(mcp_server=name).set(0)
            else:
                metrics.aion_mcp_server_healthy.labels(mcp_server=name).set(0)

    def _ensure_cleanup_task(self):
        """Avvia il task di cleanup se non è già attivo e se c'è un loop in esecuzione."""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._cleanup_task = loop.create_task(self._periodic_cleanup())
        except RuntimeError:
            # Nessun loop in esecuzione, riproveremo alla prossima chiamata
            pass

    async def _periodic_cleanup(self):
        """Spegne i worker MCP inattivi oltre AION_MCP_POOL_IDLE_SEC (0 = disabilitato)."""
        while True:
            await asyncio.sleep(60)
            try:
                idle_sec = float(os.getenv("AION_MCP_POOL_IDLE_SEC", "0"))
                if idle_sec <= 0:
                    continue
                now = asyncio.get_event_loop().time()
                to_release = []
                async with self._pool_lock:
                    for (sid, sname), worker in list(self._pool.items()):
                        if str(sid).startswith("__user__") and os.getenv(
                            "AION_MCP_USER_POOL_IDLE_CLEANUP", "0"
                        ).lower() not in ("1", "true", "yes"):
                            continue
                        if (now - worker.last_access) > idle_sec:
                            logger.info(
                                "🕒 MCP pool: rilascio worker inattivo '%s' per sessione '%s'",
                                sname,
                                sid,
                            )
                            to_release.append((sid, sname))

                for sid, sname in to_release:
                    # Rimuoviamo dal pool e spegniamo
                    async with self._pool_lock:
                        worker = self._pool.pop((sid, sname), None)
                    if worker:
                        await worker.shutdown()
            except Exception as e:
                logger.error("Error in MCP pool cleanup: %s", e)

    def _atexit_sync(self) -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return
        except RuntimeError:
            return

    def _rebuild_merged(self) -> None:
        self._registry = _merge_mcp_registries(
            self._registry_base, self._registry_local
        )

    def _load_registry_layers(self, primary_path: str) -> Dict[str, Any]:
        """YAML/JSON flat map + optional companion ``.json`` (``mcpServers`` standard)."""
        merged: Dict[str, Any] = {}
        if os.path.exists(primary_path):
            merged = load_registry_file(primary_path)
        json_path = companion_json_path(primary_path)
        if os.path.exists(json_path):
            merged = _merge_mcp_registries(merged, load_registry_file(json_path))
        if (
            not merged
            and not os.path.exists(primary_path)
            and not os.path.exists(json_path)
        ):
            logger.warning(
                "MCP registry not found at %s or %s", primary_path, json_path
            )
        return merged

    def load_registry(self, *, force: bool = False) -> None:
        base_mtime = (
            os.path.getmtime(self.registry_path)
            if os.path.exists(self.registry_path)
            else 0.0
        )
        local_mtime = (
            os.path.getmtime(self.local_registry_path)
            if os.path.exists(self.local_registry_path)
            else 0.0
        )
        pair = (base_mtime, local_mtime)
        if not force and pair == self._registry_load_mtimes and self._registry:
            return
        # Nessun expandvars al load: risoluzione in get_server_config → resolve_env_placeholders.
        self._registry_base = self._load_registry_layers(self.registry_path)

        _maybe_migrate_local_registry(self.local_registry_path)
        self._registry_local = self._load_registry_layers(self.local_registry_path)

        self._rebuild_merged()
        self._registry_load_mtimes = pair
        logger.debug(
            "MCP registry merged: %d server(s) (base=%s local=%s)",
            len(self._registry),
            self.registry_path,
            self.local_registry_path,
        )

    def invalidate_registry_cache(self) -> None:
        self._registry_load_mtimes = (0.0, 0.0)

    def save_registry(self) -> None:
        """Persiste solo il registry locale (overlay), mai il YAML base del progetto."""
        path = self.local_registry_path
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                self._registry_local,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        self.invalidate_registry_cache()
        self.load_registry(force=True)

    def _remove_from_deleted_list(self, name: str) -> None:
        rem = self._registry_local.get("_removed")
        if not rem or name not in rem:
            return
        self._registry_local["_removed"] = [x for x in rem if x != name]

    def install_stdio_server(
        self,
        name: str,
        script_path: str,
        dependencies: Optional[List[str]] = None,
    ) -> bool:
        """
        Registra un server MCP stdio nel registry locale.
        `script_path` può essere assoluto o relativo alla cwd.
        """
        _ = dependencies  # installazione venv/deps opzionale in futuro
        path = script_path
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        if not os.path.isfile(path):
            logger.error("install_stdio_server: file non trovato: %s", path)
            return False
        self._remove_from_deleted_list(name)
        self._registry_local[name] = {
            "command": "python",
            "args": ["-u", path],
            "description": f"MCP server {name}",
        }
        self._rebuild_merged()
        self.save_registry()
        return True

    def update_server_config(
        self, name: str, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Aggiorna un server nel registry locale (merge su vista già merged)."""
        if name not in self._registry:
            raise KeyError(name)
        current = copy.deepcopy(self._registry[name])
        current.update(updates)
        self._registry_local[name] = current
        self._remove_from_deleted_list(name)
        self._rebuild_merged()
        self.save_registry()
        return copy.deepcopy(self._registry[name])

    def delete_server(self, name: str) -> bool:
        """
        Rimuove un server dalla vista merged: toglie override locale; se esiste nel base,
        aggiunge il nome a `_removed` così non viene più mostrato.
        """
        if name not in self._registry:
            return False
        in_base = name in self._registry_base

        if name in self._registry_local:
            del self._registry_local[name]

        if in_base:
            rem = list(self._registry_local.get("_removed") or [])
            if name not in rem:
                rem.append(name)
            self._registry_local["_removed"] = rem

        self._rebuild_merged()
        self.save_registry()
        return True

    def import_servers_dict(self, servers: Dict[str, Any]) -> None:
        """Unisce dizionari server (es. da Claude JSON) nel registry locale."""
        for key, val in servers.items():
            if not isinstance(val, dict):
                continue
            self._registry_local[key] = copy.deepcopy(val)
            self._remove_from_deleted_list(key)
        self._rebuild_merged()
        self.save_registry()

    def get_server_config(self, name: str) -> Optional[Dict[str, Any]]:
        """Config runtime con `${VAR}` risolte da os.environ."""
        raw = self._registry.get(name)
        if raw is None:
            return None
        return resolve_env_placeholders(copy.deepcopy(raw))

    def server_exists(self, name: str) -> bool:
        return bool(name) and name in self._registry

    def get_python_exe(self, server_name: str) -> str:
        venv_path = _repo_root() / "mcp_servers" / server_name / ".venv"
        if venv_path.exists():
            if sys.platform == "win32":
                return str(venv_path / "Scripts" / "python.exe")
            return str(venv_path / "bin" / "python3")
        return sys.executable

    def set_session_context(self, conversation_id: str, ctx) -> None:
        from .runtime.session_context import SessionContext

        if isinstance(ctx, SessionContext):
            self._session_ctx[conversation_id] = ctx.as_tuple()
        else:
            self._session_ctx[conversation_id] = ctx

    def get_session_context(self, conversation_id: str):
        from .runtime.session_context import SessionContext

        raw = self._session_ctx.get(conversation_id or "")
        if not raw:
            return None
        return SessionContext.from_tuple(conversation_id, raw)

    def _ensure_health_metric(self, server_name: str) -> None:
        label_tuple = (server_name,)
        if label_tuple in self._health_labels_initialized:
            return
        try:
            metrics.aion_mcp_server_healthy.labels(mcp_server=server_name).set(0)
            self._health_labels_initialized.add(label_tuple)
        except Exception as e:
            logger.warning(
                "Failed to initialize health metric for %s: %s", server_name, e
            )

    @staticmethod
    def resolve_stdio_script_path(arg: str) -> Optional[str]:
        """Absolute path to a stdio MCP entrypoint script, or None if not found."""
        if not isinstance(arg, str) or arg.startswith("-") or not arg.endswith(".py"):
            return None
        if os.path.isabs(arg) and os.path.isfile(arg):
            return arg
        root = _repo_root()
        cwd = os.getcwd()
        candidates = [
            os.path.abspath(os.path.join(cwd, "mcp_servers", arg)),
            os.path.abspath(os.path.join(root, "mcp_servers", arg)),
            os.path.abspath(os.path.join(cwd, arg)),
            os.path.abspath(os.path.join(root, arg)),
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path
        return None

    @classmethod
    def resolve_stdio_args(cls, args: List[str]) -> List[str]:
        """Risolve path di file sotto ``mcp_servers/`` o repo root; non convertire flag."""
        root = _repo_root()
        resolved: List[str] = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--directory" and i + 1 < len(args):
                resolved.append(arg)
                dir_arg = args[i + 1]
                dir_path = Path(dir_arg)
                if not dir_path.is_absolute():
                    cand = (root / dir_arg).resolve()
                    resolved.append(str(cand) if cand.is_dir() else dir_arg)
                else:
                    resolved.append(dir_arg)
                i += 2
                continue
            if (
                isinstance(arg, str)
                and not arg.startswith("/")
                and not arg.startswith("-")
            ):
                script = cls.resolve_stdio_script_path(arg)
                resolved.append(script if script else arg)
            else:
                resolved.append(arg)
            i += 1
        return resolved

    @classmethod
    def stdio_entrypoint_missing(
        cls, server_name: str, config: Dict[str, Any]
    ) -> Optional[str]:
        """Return human-readable reason if the stdio server script is missing."""
        t = (config.get("type") or "stdio").lower()
        if t in ("sse", "in_process"):
            return None
        if t == "remote-bridge":
            local_path = os.path.join(
                os.getcwd(), "node_modules", "mcp-remote", "dist", "proxy.js"
            )
            if os.path.exists(local_path):
                if not shutil.which("node"):
                    return "node command not found. Node.js is required to run remote-bridge."
                return None
            if not shutil.which("npx"):
                return "npx command not found and local mcp-remote not installed. Node.js/npm is required to run remote-bridge."
            return None
        args = list(config.get("args") or [])
        for arg in args:
            if isinstance(arg, str) and arg.endswith(".py") and not arg.startswith("-"):
                if cls.resolve_stdio_script_path(arg):
                    return None
                return (
                    f"script {arg!r} not found (tried mcp_servers/ and repo root). "
                    f"Install the {server_name} MCP server or remove it from "
                    "profile.mcp_servers / config/mcp_registry.local.yaml"
                )
        return None

    def _is_stdio_server(self, name: str) -> bool:
        cfg = self.get_server_config(name)
        if not cfg:
            return False
        t = (cfg.get("type") or "stdio").lower()
        return t not in ("sse", "in_process")

    def _resolve_pool_key(
        self, chat_session_id: str, server_name: str
    ) -> Tuple[str, str]:
        """Pool key: session-scoped servers isolate per chat; others share user pool."""
        if not _USE_POOL:
            return (chat_session_id, server_name)
        if server_name in _session_scoped_servers() and chat_session_id:
            return (chat_session_id, server_name)
        if not _user_pool_enabled():
            return (chat_session_id, server_name)
        ctx = self._session_ctx.get(chat_session_id) or self._session_ctx.get(
            BOOTSTRAP_SESSION_ID
        )
        if not ctx:
            return (chat_session_id, server_name)
        if len(ctx) == 2:
            _, uid = ctx
            tid = "default"
        else:
            _, uid, tid = ctx
        safe_uid = sanitize_user_id(uid)
        tid = (tid or "default").strip() or "default"
        return (f"__user__{safe_uid}__{tid}", server_name)

    async def _get_worker(
        self, chat_session_id: str, server_name: str
    ) -> MCPStdioWorker:
        if os.getenv("AION_MCP_POOL", "0").lower() in ("0", "false", "no"):
            self._ensure_cleanup_task()
        key = self._resolve_pool_key(chat_session_id, server_name)
        worker_session_id = chat_session_id if key[0] == chat_session_id else ""
        pool_identity = _parse_user_pool_key(key[0])
        async with self._pool_lock:
            if key not in self._pool:
                pool_uid, pool_tid = pool_identity if pool_identity else (None, None)
                self._pool[key] = MCPStdioWorker(
                    self,
                    server_name,
                    worker_session_id,
                    pool_user_id=pool_uid,
                    pool_tenant_id=pool_tid,
                )
            return self._pool[key]

    async def _warm_credentials_missing(
        self, chat_session_id: str, server_name: str
    ) -> Optional[str]:
        """Skip warm when per-user MCP env placeholders resolve to empty strings."""
        cfg = self.get_server_config(server_name)
        if not cfg:
            return None
        env_block = cfg.get("env")
        if not env_block or not isinstance(env_block, dict):
            return None
        ctx = self._session_ctx.get(chat_session_id)
        if not ctx:
            return None
        if len(ctx) == 2:
            _, uid = ctx
            tid = "default"
        else:
            _, uid, tid = ctx
        try:
            from .runtime.credential_store import resolve_mcp_env_for_user

            resolved = await resolve_mcp_env_for_user(
                env_block,
                user_id=sanitize_user_id(uid),
                tenant_id=(tid or "default").strip() or "default",
                server_slug=server_name,
            )
        except Exception as exc:
            logger.debug("MCP warm credential check failed %s: %s", server_name, exc)
            return None
        for key, template in env_block.items():
            if not isinstance(template, str):
                continue
            needs_user_cred = "${AION_USER_" in template
            val = resolved.get(key)
            if needs_user_cred and (
                val is None or (isinstance(val, str) and not val.strip())
            ):
                return f"credenziali mancanti per {server_name} ({key})"
        return None

    async def _pre_materialize_office_skills(
        self, chat_session_id: str, profile_slug: str
    ) -> None:
        """Copy office skill scripts into the session before the first docx exec."""
        try:
            from .agent_profile import profile_manager
            from .tools.skill_materialize import (
                OFFICE_SKILL_SLUGS,
                materialize_skill_scripts,
            )

            # Eseguiamo il caricamento dei profili in un thread per non bloccare l'event loop.
            def load_profile():
                profile_manager.load_all()
                return profile_manager.get_profile(profile_slug)

            profile = await asyncio.to_thread(load_profile)
            if not profile or not profile.skills:
                return

            skills_to_materialize = [
                slug for slug in OFFICE_SKILL_SLUGS if slug in profile.skills
            ]

            if skills_to_materialize:
                # Eseguiamo la materializzazione concorrente in thread in modo non bloccante per l'event loop.
                # L'agente attenderà il completamento della materializzazione prima di procedere.
                tasks = [
                    asyncio.to_thread(materialize_skill_scripts, chat_session_id, slug)
                    for slug in skills_to_materialize
                ]
                await asyncio.gather(*tasks)
        except Exception as exc:
            logger.warning(
                "office skill pre-materialize failed session=%s profile=%s: %s",
                chat_session_id[:8],
                profile_slug,
                exc,
            )

    async def warm_session(
        self,
        chat_session_id: str,
        server_names: List[str],
        *,
        profile_slug: str = "generic_assistant",
        user_id: str = "default",
        tenant_id: str = "default",
    ) -> None:
        """Pre-connette tutti gli MCP stdio del profilo per questa chat session."""
        self.load_registry()
        from .runtime.session_context import SessionContext

        old_ctx = self._session_ctx.get(chat_session_id)
        old_profile_slug = None
        if old_ctx:
            if len(old_ctx) == 2:
                old_profile_slug, _ = old_ctx
            else:
                old_profile_slug, _, _ = old_ctx

        self.set_session_context(
            chat_session_id,
            SessionContext(
                profile_slug=profile_slug,
                user_id=user_id,
                tenant_id=tenant_id,
                conversation_id=chat_session_id,
            ),
        )
        try:
            for name in server_names:
                cfg = self.get_server_config(name)
                if cfg and cfg.get("type") == "in_process":
                    continue
                self._ensure_health_metric(name)
        except Exception as e:
            logger.warning("Failed to initialize health metrics in warm_session: %s", e)

        # Rilascia worker non più nel profilo (session-scoped o user-pool condiviso).
        try:
            to_stop = []
            user_pool_key = f"__user__{sanitize_user_id(user_id)}__{(tenant_id or 'default').strip() or 'default'}"
            async with self._pool_lock:
                for (sid, sname), worker in list(self._pool.items()):
                    if sid == chat_session_id:
                        if sname not in server_names:
                            to_stop.append((sid, sname))
                        elif old_profile_slug and old_profile_slug != profile_slug:
                            to_stop.append((sid, sname))
                    elif sid == user_pool_key and sname not in server_names:
                        # Worker user-pool restano caldi tra profili/chat (startup warm).
                        pass
                    elif not str(sid).startswith("__user__"):
                        ctx = self._session_ctx.get(sid)
                        if ctx:
                            if len(ctx) == 2:
                                p_slug, uid = ctx
                            else:
                                p_slug, uid, _tid = ctx
                            if uid == user_id and p_slug != profile_slug:
                                to_stop.append((sid, sname))

            for sid, sname in to_stop:
                logger.info(
                    "Profilo cambiato: rilascio worker '%s' della sessione '%s' non più presente/attivo",
                    sname,
                    sid,
                )
                async with self._pool_lock:
                    worker = self._pool.pop((sid, sname), None)
                if worker:
                    await worker.shutdown()
        except Exception as e:
            logger.warning(
                "Errore durante il rilascio dei vecchi worker nel cambio profilo/sessione: %s",
                e,
            )

        if not _USE_POOL:
            return

        async def _warm_one(name: str) -> None:
            if not self._is_stdio_server(name):
                return
            pool_sid = self._resolve_pool_key(chat_session_id, name)[0]
            if self._warm_circuit_open(pool_sid, name):
                msg = self._warm_failure_message(pool_sid, name)
                logger.debug(
                    "MCP warm skip (circuit) server=%s pool=%s",
                    name,
                    pool_sid[:16],
                )
                try:
                    from .runtime.mcp_health import record_mcp_load_error

                    record_mcp_load_error(chat_session_id, name, msg)
                except Exception:
                    pass
                return
            if self._is_server_healthy(chat_session_id, name):
                key = self._resolve_pool_key(chat_session_id, name)
                worker = self._pool.get(key)
                if worker is not None:
                    worker.last_access = asyncio.get_event_loop().time()
                return
            cfg = self.get_server_config(name)
            if cfg:
                missing = self.stdio_entrypoint_missing(name, cfg)
                if missing:
                    logger.warning("MCP warm skip %s: %s", name, missing)
                    try:
                        from .runtime.mcp_health import record_mcp_load_error

                        record_mcp_load_error(chat_session_id, name, missing)
                    except Exception:
                        pass
                    return
            cred_missing = await self._warm_credentials_missing(chat_session_id, name)
            if cred_missing:
                logger.info("MCP warm skip %s: %s", name, cred_missing)
                self._record_warm_failure(pool_sid, name, cred_missing)
                try:
                    from .runtime.mcp_health import record_mcp_load_error

                    record_mcp_load_error(chat_session_id, name, cred_missing)
                except Exception:
                    pass
                return
            async with self._warm_lock(pool_sid, name):
                if self._is_server_healthy(chat_session_id, name):
                    return
                if self._warm_circuit_open(pool_sid, name):
                    return
                w = await self._get_worker(chat_session_id, name)
                retry = (pool_sid, name) in self._warm_failures
                warm_timeout = self._warm_timeout_sec(retry=retry)
                try:
                    await asyncio.wait_for(w.start(), timeout=warm_timeout)
                except asyncio.TimeoutError:
                    msg = f"MCP warm timeout {int(warm_timeout)}s"
                    logger.warning(
                        "MCP warm timeout server=%s session=%s",
                        name,
                        chat_session_id[:8],
                    )
                    self._record_warm_failure(pool_sid, name, msg)
                    try:
                        from .runtime.mcp_health import record_mcp_load_error

                        record_mcp_load_error(chat_session_id, name, msg)
                    except Exception:
                        pass
                    return
                if w._init_error is not None:
                    err = str(w._init_error).strip() or type(w._init_error).__name__
                    self._record_warm_failure(pool_sid, name, err)
                    try:
                        from .runtime.mcp_health import record_mcp_load_error

                        record_mcp_load_error(chat_session_id, name, err)
                    except Exception:
                        pass
                    return
                self._clear_warm_failure(pool_sid, name)

        stdio_names = [n for n in server_names if self._is_stdio_server(n)]
        if stdio_names:
            await asyncio.gather(
                *[_warm_one(n) for n in stdio_names], return_exceptions=True
            )
            logger.info(
                "MCP pool warm per session=%s servers=%s",
                chat_session_id[:8] + "...",
                stdio_names,
            )
        await self._pre_materialize_office_skills(chat_session_id, profile_slug)
        # TODO(multi-worker): warm MCP pool / agent cache in Redis to avoid thundering herd across workers.

    async def restart_worker(self, chat_session_id: str, server_name: str) -> None:
        """Kill pooled stdio worker (e.g. after hung PostgreSQL query)."""
        key = self._resolve_pool_key(chat_session_id, server_name)
        async with self._pool_lock:
            w = self._pool.pop(key, None)
        if w is None:
            return
        if w._task and not w._task.done():
            w._task.cancel()
        try:
            await asyncio.wait_for(
                w.shutdown(),
                timeout=float(os.getenv("AION_MCP_WORKER_SHUTDOWN_TIMEOUT", "15")),
            )
        except asyncio.TimeoutError:
            logger.warning(
                "MCP worker '%s' shutdown slow after timeout; pool entry dropped",
                server_name,
            )

    async def call_tool_pooled(
        self,
        chat_session_id: str,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ):
        sid = (chat_session_id or "").strip()
        if (not sid or sid == "default") and server_name in _session_scoped_servers():
            from .runtime.context import get_current_session_id

            sid = (get_current_session_id() or sid or "").strip()
        if server_name == "mempalace":
            from .runtime.mempalace_tool_scope import mempalace_write_blocked_message

            blocked = mempalace_write_blocked_message(tool_name)
            if blocked:
                raise RuntimeError(blocked)
        if not _USE_POOL or not self._is_stdio_server(server_name):
            async with self.session_context(
                server_name, chat_session_id=sid or None
            ) as session:
                return await session.call_tool(name=tool_name, arguments=arguments)
        w = await self._get_worker(sid, server_name)
        try:
            result = await w.call_tool(tool_name, arguments, chat_session_id=sid)
            # Tool call succeeded → clear any warm-up timeout error for this server.
            from .runtime.mcp_health import clear_mcp_load_errors

            clear_mcp_load_errors(sid, server_name)
            return result
        except (TimeoutError, asyncio.TimeoutError):
            await self.restart_worker(sid, server_name)
            raise

    async def list_tools_pooled(self, chat_session_id: str, server_name: str):
        if not _USE_POOL or not self._is_stdio_server(server_name):
            async with self.session_context(
                server_name, chat_session_id=None
            ) as session:
                return await session.list_tools()
        w = await self._get_worker(chat_session_id, server_name)
        return await w.list_tools()

    async def release_session(self, chat_session_id: str) -> None:
        async with self._pool_lock:
            to_del = [
                k
                for k in self._pool
                if k[0] == chat_session_id and not str(k[0]).startswith("__user__")
            ]
            workers = [self._pool.pop(k) for k in to_del]
        for w in workers:
            await w.shutdown()

    @asynccontextmanager
    async def session_context(self, name: str, chat_session_id: Optional[str] = None):
        """
        Se chat_session_id è valorizzato e AION_MCP_POOL=1 e server stdio → usa il worker in pool.
        Altrimenti sessione effimera (SSE o pool disattivato).
        """
        self.load_registry()
        config = self.get_server_config(name)

        # Inizializza la metrica di salute a 0 se non esiste già ed è un server esterno (non in_process)
        try:
            if not config or config.get("type") != "in_process":
                self._ensure_health_metric(name)
        except Exception as e:
            logger.warning(
                "Failed to initialize health metric in session_context: %s", e
            )

        if not config:
            raise ValueError(f"MCP server '{name}' not found in registry")

        if chat_session_id and _USE_POOL and self._is_stdio_server(name):
            w = await self._get_worker(chat_session_id, name)
            await w.start()

            class _SessionProxy:
                async def list_tools(self_inner):
                    return await w.list_tools()

                async def call_tool(
                    self_inner, name: str, arguments: Optional[Dict[str, Any]] = None
                ):
                    return await w.call_tool(
                        name, arguments or {}, chat_session_id=chat_session_id
                    )

            yield _SessionProxy()
            return

        server_type = (config.get("type") or "stdio").lower()
        if server_type == "in_process":
            raise RuntimeError(
                f"MCP server '{name}' è type=in_process: i tool sono registrati in-process, "
                "non usare session_context."
            )
        if server_type == "sse":
            url = config.get("url")
            if not url:
                raise ValueError(f"URL missing for SSE server '{name}'")
            token = await khub_token_manager.get_token()
            headers = {"Authorization": f"Bearer {token}"} if token else {}

            # Resolve user-specific environment variables for headers/credentials
            if chat_session_id:
                ctx = self._session_ctx.get(
                    chat_session_id, ("generic_assistant", "default", "default")
                )
                if len(ctx) == 2:
                    slug, uid = ctx
                    tid = "default"
                else:
                    slug, uid, tid = ctx
            else:
                slug, uid, tid = "generic_assistant", "default", "default"

            resolved_env = {}
            if "env" in config:
                from .runtime.credential_store import resolve_mcp_env_for_user

                resolved_env = await resolve_mcp_env_for_user(
                    config.get("env"),
                    user_id=sanitize_user_id(uid),
                    tenant_id=tid,
                    server_slug=name,
                )
            if "OAUTH_TOKEN" not in resolved_env:
                from .runtime.credential_store import get_credential

                oauth_tok = await get_credential(
                    sanitize_user_id(uid), name, "OAUTH_TOKEN", tenant_id=tid
                )
                if oauth_tok:
                    resolved_env["OAUTH_TOKEN"] = oauth_tok

            config_headers = config.get("headers") or {}
            remotes = config.get("remotes") or []
            if not config_headers and remotes:
                for r in remotes:
                    if isinstance(r, dict) and r.get("url") == url:
                        raw_h = r.get("headers")
                        if isinstance(raw_h, dict):
                            config_headers = raw_h
                        elif isinstance(raw_h, list):
                            config_headers = {
                                str(item.get("name")): str(item.get("value"))
                                for item in raw_h
                                if isinstance(item, dict)
                            }
                        break

            for h_name, h_val in config_headers.items():
                val_str = str(h_val)
                for k, v in resolved_env.items():
                    val_str = val_str.replace(f"${{{k}}}", str(v))
                for k, v in os.environ.items():
                    val_str = val_str.replace(f"${{{k}}}", str(v))
                headers[h_name] = val_str

            if "Authorization" not in headers:
                if resolved_env.get("OAUTH_TOKEN"):
                    headers["Authorization"] = f"Bearer {resolved_env['OAUTH_TOKEN']}"
                elif resolved_env.get("API_KEY"):
                    headers["Authorization"] = f"Bearer {resolved_env['API_KEY']}"
                elif resolved_env.get("BASIC_AUTH"):
                    headers["Authorization"] = f"Basic {resolved_env['BASIC_AUTH']}"

            logger.debug(
                "Connecting to SSE MCP: %s at %s (auth_headers=%s)",
                name,
                url,
                list(headers.keys()),
            )
            is_active = False
            try:
                async with sse_client(url, headers=headers) as (r, w):
                    session = ClientSession(r, w)
                    async with session:
                        await session.initialize()
                        await self._increment_active_server(name)
                        is_active = True
                        yield session
            except Exception:
                raise
            finally:
                if is_active:
                    await self._decrement_active_server(name)
                else:
                    metrics.aion_mcp_server_healthy.labels(mcp_server=name).set(0)

            async with sse_client(url, headers=headers) as (r, w):
                session = ClientSession(r, w)
                async with session:
                    await session.initialize()
                    yield session

        else:
            command = config.get("command", "python")
            if command == "python":
                command = self.get_python_exe(name)
            elif isinstance(command, str) and (
                "/" in command or os.path.sep in command
            ):
                cmd_path = Path(command)
                if not cmd_path.is_absolute():
                    cand = _repo_root() / command
                    if cand.is_file():
                        command = str(cand.resolve())
            args = self.resolve_stdio_args(list(config.get("args", [])))
            env = os.environ.copy()
            project_root = os.getcwd()
            env.setdefault("FASTMCP_LOG_LEVEL", "WARNING")
            env.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")
            env.setdefault("FASTMCP_CHECK_FOR_UPDATES", "true")
            env.setdefault("NO_COLOR", "1")
            env.setdefault("TQDM_DISABLE", "1")
            env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            env["PYTHONPATH"] = f"{project_root}:{env.get('PYTHONPATH', '')}"
            if chat_session_id:
                env["AION_CHAT_SESSION_ID"] = chat_session_id
                ctx = self._session_ctx.get(
                    chat_session_id, ("generic_assistant", "default", "default")
                )
                if len(ctx) == 2:
                    slug, uid = ctx
                    tid = "default"
                else:
                    slug, uid, tid = ctx
            else:
                slug, uid, tid = "generic_assistant", "default", "default"
            env["AION_CURRENT_PROFILE_SLUG"] = slug
            env["AION_CURRENT_USER_ID"] = uid
            env["AION_CURRENT_TENANT_ID"] = tid
            _apply_mcp_home_isolation(env, uid)
            if name == "mempalace":
                apply_shared_embedding_cache_env(env)
                from .memory.project_memory_scope import apply_mempalace_palace_env

                apply_mempalace_palace_env(env, tid)
            if "env" in config:
                from .runtime.credential_store import resolve_mcp_env_for_user

                resolved_server_env = await resolve_mcp_env_for_user(
                    config.get("env"),
                    user_id=sanitize_user_id(uid),
                    tenant_id=tid,
                    server_slug=name,
                )
                if name == "mcp-email-server" or "email" in name:
                    resolved_server_env = normalize_mcp_email_server_env(
                        resolved_server_env
                    )
                _merge_mcp_subprocess_env(env, resolved_server_env)
            apply_runtime_env_aliases(env, name, config)
            _adjust_stdio_spawn_env(env, command)
            server_params = StdioServerParameters(command=command, args=args, env=env)
            init_timeout = float(os.getenv("AION_MCP_INIT_TIMEOUT", "60"))
            is_active = False
            try:
                async with stdio_client(server_params) as (r, w):
                    session = ClientSession(r, w)
                    async with session:
                        await asyncio.wait_for(
                            session.initialize(), timeout=init_timeout
                        )
                        await self._increment_active_server(name)
                        is_active = True
                        yield session
            except Exception as e:
                raise e
            finally:
                if is_active:
                    await self._decrement_active_server(name)
                else:
                    metrics.aion_mcp_server_healthy.labels(mcp_server=name).set(0)

    async def get_session_by_name(self, name: str) -> ClientSession:
        logger.warning("get_session_by_name called for '%s'. Deprecated.", name)
        raise RuntimeError(
            "get_session_by_name is incompatible with ephemeral mode. Use session_context()."
        )

    def get_all_servers(self) -> List[str]:
        return list(self._registry.keys())


def _format_mcp_tool_result(res: Any) -> str:
    from .runtime.mcp_tool_result import format_mcp_raw_result

    return format_mcp_raw_result(res)


class SerializableMCPTool:
    def __init__(
        self, server_name: str, tool_name: str, chat_session_id: str = "default"
    ):
        self.server_name = server_name
        self.tool_name = tool_name
        self.chat_session_id = chat_session_id

    def __call__(self, **kwargs):
        from .main import _GLOBAL_LOOP as main_loop

        loop = main_loop
        if not loop:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                pass
        if not loop:
            raise RuntimeError("No event loop found to execute MCP tool.")

        async def call_mcp():
            from .runtime.pg_query_guard import postgres_query_timeout_sec

            # Pop _trace_context to avoid Pydantic validation errors in MCP servers
            # that don't expect it as a tool parameter.
            prepared = dict(kwargs)
            prepared.pop("_trace_context", None)
            if self.server_name == "mempalace":
                from .runtime.mempalace_tool_scope import (
                    apply_mempalace_project_scope,
                    mempalace_write_blocked_message,
                )

                blocked = mempalace_write_blocked_message(self.tool_name)
                if blocked:
                    raise RuntimeError(blocked)
                prepared = apply_mempalace_project_scope(self.tool_name, prepared)
            if self.server_name in ("memory", "query_memory"):
                from .runtime.sql_query_project_scope import (
                    apply_sql_query_project_scope,
                    block_project_list_tool,
                )

                blocked = block_project_list_tool(self.tool_name, self.chat_session_id)
                if blocked:
                    raise RuntimeError(blocked)
                prepared = apply_sql_query_project_scope(
                    self.tool_name, prepared, session_id=self.chat_session_id
                )

            use_pool = getattr(sys.modules[__name__], "_USE_POOL", False)
            clean = sanitize_mcp_tool_arguments(prepared)

            sid = (self.chat_session_id or "").strip()
            if not sid or sid == "default":
                from .runtime.context import get_current_session_id

                sid = (get_current_session_id() or sid or "").strip()

            async def _invoke():
                if use_pool and mcp_manager._is_stdio_server(self.server_name):
                    return await mcp_manager.call_tool_pooled(
                        sid, self.server_name, self.tool_name, clean
                    )
                async with mcp_manager.session_context(
                    self.server_name, chat_session_id=sid or None
                ) as sess:
                    return await sess.call_tool(name=self.tool_name, arguments=clean)

            # Pooled stdio workers enforce PG timeout internally; avoid double wait_for.
            q_timeout = postgres_query_timeout_sec(self.server_name, self.tool_name)
            pooled_pg = (
                use_pool
                and mcp_manager._is_stdio_server(self.server_name)
                and q_timeout is not None
            )
            if q_timeout and not pooled_pg:
                raw = await asyncio.wait_for(_invoke(), timeout=q_timeout)
            else:
                raw = await _invoke()
            text = _format_mcp_tool_result(raw)
            if self.server_name == "mempalace":
                from .runtime.mempalace_tool_scope import enrich_mempalace_tool_result

                text = enrich_mempalace_tool_result(self.tool_name, text)
            return text

        if loop.is_closed():
            raise RuntimeError(
                f"MCP event loop is closed; cannot run {self.server_name}/{self.tool_name}"
            )
        timeout_sec = float(os.getenv("AION_MCP_TOOL_RESULT_TIMEOUT", "120"))
        future = asyncio.run_coroutine_threadsafe(call_mcp(), loop)
        try:
            return future.result(timeout=timeout_sec)
        except TimeoutError as exc:
            from .runtime.pg_query_guard import (
                is_postgres_query_tool,
                postgres_query_timeout_sec,
            )

            if (
                _USE_POOL
                and mcp_manager._is_stdio_server(self.server_name)
                and is_postgres_query_tool(self.server_name, self.tool_name)
            ):
                try:
                    asyncio.run_coroutine_threadsafe(
                        mcp_manager.restart_worker(
                            self.chat_session_id, self.server_name
                        ),
                        loop,
                    ).result(timeout=20)
                except Exception as restart_exc:
                    logger.debug(
                        "MCP worker restart after timeout failed: %s", restart_exc
                    )
            q_cap = postgres_query_timeout_sec(self.server_name, self.tool_name)
            cap = q_cap if q_cap else timeout_sec
            raise TimeoutError(
                f"MCP {self.server_name}/{self.tool_name} timed out after {cap:g}s"
            ) from exc


mcp_manager = MCPManager()
