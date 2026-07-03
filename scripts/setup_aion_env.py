#!/usr/bin/env python3
"""
Setup guidato per ``.env`` (AION Agent): modalità **semplice** o **avanzata**.

  ./scripts/setup-aion-env.sh                     # wizard shell (menu + colori)
  python scripts/setup_aion_env.py              # chiede la modalità
  python scripts/setup_aion_env.py --simple
  python scripts/setup_aion_env.py --advanced
  python scripts/setup_aion_env.py --dry-run    # anteprima senza scrivere file
  python scripts/setup_aion_env.py --import-state FILE -y   # merge da script
  python scripts/check_env_example_coverage.py              # audit .env.example vs src + settings + upgrade

Quando il login chat e' abilitato (``AION_CHAT_PASSWORD_AUTH``), dopo la scrittura del
``.env`` viene eseguito il bootstrap del DB + creazione utente (interattivo senza ``-y``;
con ``-y`` usare ``AION_SETUP_CHAT_*`` nel file importato).

Le chiavi gestite sono quelle presenti in ``.env.example``; le altre chiavi in un ``.env``
esistente vengono preservate in coda sotto un blocco commentato.
``./scripts/upgrade-aion.sh`` (``upgrade_core._ensure_*_env_keys``) appende in ``.env`` le chiavi
mancanti (web search, context compress, tool-first runtime ``AION_MODEL_PROMPT_FRAGMENTS`` /
``AION_ARTIFACT_STREAM_LEGACY`` / ``AION_STREAM_LOOP_V2`` / doom loop / vLLM tool args /
``AION_LLM_CALL_AUDIT``, SQL QueryMemory ``AION_SQL_QM_*``,
MemPalace navigazione ``AION_MEMPALACE_NAV_*``, allowlist ``skill_view`` ``AION_SKILL_VIEW_ENFORCE_PROFILE``, …).
``setup_core.py`` / ``upgrade_core.py`` applicano anche ``patch_sql_query_memory_config.py`` e
``patch_mempalace_navigation_config.py`` (profilo Postgres, skill, wing ``wing_proj_{project}``).
Bootstrap opzionale drawer: ``python scripts/bootstrap_db_navigation_mempalace.py --project default``.

Il client principale e' ``chat-ui/`` (Next.js). I flag legacy ``AION_CHAINLIT_*``
/ ``CHAINLIT_AUTH_SECRET`` sono ancora migrati automaticamente in ``AION_CHAT_*``
(fallback in ``src/api/auth_login.py``).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).absolute().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_EXAMPLE = _REPO_ROOT / ".env.example"


def _read_version() -> str:
    """Legge la versione dal file centralizzato version.json nella root del repo."""
    try:
        import json
        version_file = _REPO_ROOT / "version.json"
        return json.loads(version_file.read_text(encoding="utf-8")).get("version", "unknown")
    except Exception:
        return "unknown"

# Chiavi legacy lette dal codice come fallback ma NON scritte nei nuovi .env
# (la migrazione viene fatta da scripts/upgrade_core.py).
# Mantenute in .env.example come righe attive per soddisfare il check di
# copertura (scripts/check_env_example_coverage.py).
_DEPRECATED_KEYS: frozenset = frozenset({
    "AION_CHAINLIT_PASSWORD_AUTH",   # → AION_CHAT_PASSWORD_AUTH
    "CHAINLIT_AUTH_SECRET",          # → AION_CHAT_AUTH_SECRET
    "AION_SETUP_CHAINLIT_IDENTIFIER",# → AION_SETUP_CHAT_IDENTIFIER
    "AION_SETUP_CHAINLIT_PASSWORD",  # → AION_SETUP_CHAT_PASSWORD
})

# Mapping autoritativo old -> new (consumato anche da upgrade_core.py)
LEGACY_RENAME: Dict[str, str] = {
    "AION_CHAINLIT_PASSWORD_AUTH": "AION_CHAT_PASSWORD_AUTH",
    "CHAINLIT_AUTH_SECRET": "AION_CHAT_AUTH_SECRET",
    "AION_SETUP_CHAINLIT_IDENTIFIER": "AION_SETUP_CHAT_IDENTIFIER",
    "AION_SETUP_CHAINLIT_PASSWORD": "AION_SETUP_CHAT_PASSWORD",
}


def _parse_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = path.read_text(encoding="latin-1")
        except Exception:
            return out
            
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        key = k.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        v = v.strip().strip('"').strip("'")
        if " #" in v and not v.startswith('"'):
            v = v.split(" #", 1)[0].rstrip()
        out[key] = v
    return out


def _managed_keys() -> frozenset[str]:
    """Tutte le chiavi attive in .env.example (inclusi alias deprecati).

    Usato da scripts/check_env_example_coverage.py per verificare che ogni
    ``os.getenv`` in src/ sia coperta da .env.example.
    """
    return frozenset(_parse_env_file(_EXAMPLE).keys())


def _writable_keys() -> frozenset:
    """Chiavi effettivamente scritte nei .env generati dal wizard.

    Esclude gli alias deprecati elencati in ``_DEPRECATED_KEYS`` per evitare
    di ripopolarli ad ogni re-run. Il codice legge ancora le legacy come
    fallback finche' la deprecation non sara' rimossa.
    """
    return _managed_keys() - _DEPRECATED_KEYS


def _format_env_value(v: str) -> str:
    if "\n" in v or "\r" in v:
        raise ValueError("Valori multilinea non supportati in questo setup.")
    if v == "":
        return ""
    if re.search(r'[\s#"\'\\]', v) or v.startswith("="):
        esc = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{esc}"'
    return v


def _prompt_str(label: str, default: str, *, secret: bool = False, help_text: str = "") -> str:
    hint = f" [{default}]" if default and not secret else ""
    if help_text:
        print(f"  ({help_text})")
    try:
        if secret:
            p = getpass.getpass(f"{label}{hint}: ").strip()
        else:
            p = input(f"{label}{hint}: ").strip()
        return p if p else default
    except (EOFError, KeyboardInterrupt):
        print("\nInterrotto.")
        sys.exit(1)


def _prompt_yesno(message: str, default: bool = True) -> bool:
    d = "S/n" if default else "s/N"
    try:
        r = input(f"{message} [{d}]: ").strip().lower()
        if not r:
            return default
        return r in ("s", "si", "y", "yes", "1", "true")
    except (EOFError, KeyboardInterrupt):
        print("\nInterrotto.")
        sys.exit(1)


def _prompt_choice(message: str, choices: List[str], default: str) -> str:
    if default not in choices:
        default = choices[0]
    print(message)
    for i, c in enumerate(choices, 1):
        mark = "*" if c == default else " "
        print(f"  {mark} {i}) {c}")
    try:
        raw = input(f"Scegli (1-{len(choices)}, invio = {default}): ").strip()
        if not raw:
            return default
        try:
            idx = int(raw)
            if 1 <= idx <= len(choices):
                return choices[idx - 1]
        except ValueError:
            pass
        if raw in choices:
            return raw
        return default
    except (EOFError, KeyboardInterrupt):
        print("\nInterrotto.")
        sys.exit(1)


def _chat_auth_secret() -> str:
    return secrets.token_hex(32)


def _backup_env(env_path: Path) -> Optional[Path]:
    if not env_path.is_file():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # FIX: Non usare with_suffix perché per .env (senza stem) sostituisce l'intero nome
    bak = env_path.parent / (env_path.name + f".bak.{ts}")
    try:
        shutil.copy2(env_path, bak)
        return bak
    except Exception as e:
        print(f"ATTENZIONE: Impossibile creare backup {bak}: {e}")
        return None


def _build_write_blocks(managed: Dict[str, str], preserved: Dict[str, str]) -> str:
    lines: List[str] = [
        "# =============================================================================",
        "# AION Agent — .env (generato / aggiornato da scripts/setup_aion_env.py)",
        f"# Chiavi gestite: {len(managed)} | preservate da .env precedente: {len(preserved)}",
        "# =============================================================================",
        "",
    ]
    for key in sorted(managed.keys()):
        val = managed[key]
        if val == "":
            lines.append(f"{key}=")
        else:
            lines.append(f"{key}={_format_env_value(val)}")
    if preserved:
        lines.extend(
            [
                "",
                "# -----------------------------------------------------------------------------",
                "# Valori non coperti dal setup (preservati dal .env precedente)",
                "# -----------------------------------------------------------------------------",
            ]
        )
        for key in sorted(preserved.keys()):
            pv = preserved[key]
            lines.append(f"{key}=" if pv == "" else f"{key}={_format_env_value(pv)}")
    lines.append("")
    return "\n".join(lines)


def _write_env(env_path: Path, managed: Dict[str, str], dry_run: bool) -> Tuple[str, Optional[Path]]:
    # writable = managed - deprecated: gli alias legacy non vengono ripopolati
    # nei nuovi .env (il codice li legge come fallback finché esistono nel .env
    # dell'utente; upgrade_core.py li migra automaticamente).
    writable_keys = _writable_keys()
    managed_out = {k: managed[k] for k in writable_keys if k in managed}
    old = _parse_env_file(env_path)
    preserved = {
        k: v for k, v in old.items()
        if k not in managed_out and k not in _DEPRECATED_KEYS
    }
    body = _build_write_blocks(managed_out, preserved)
    if dry_run:
        return body, None
    bak = _backup_env(env_path)
    try:
        # Usa newline='\n' per evitare \r\n su Windows se non desiderato, 
        # o lascia gestire a Python (newline=None) per compatibilità nativa.
        # Qui forziamo '\n' per coerenza cross-platform.
        with env_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    except Exception as e:
        print(f"ERRORE FATALE: Impossibile scrivere su {env_path}: {e}")
        sys.exit(1)
    return body, bak


def _initial_state() -> Dict[str, str]:
    if not _EXAMPLE.is_file():
        print(f"ERRORE: manca {_EXAMPLE}", file=sys.stderr)
        sys.exit(1)
    state = dict(_parse_env_file(_EXAMPLE))
    env_path = _REPO_ROOT / ".env"
    if env_path.is_file():
        for k, v in _parse_env_file(env_path).items():
            state[k] = v
    return state


_DOCKER_DEFAULTS: Dict[str, str] = {
    "AION_REDIS_URL": "redis://redis:6379/0",
    "AION_DATA_DIR": "/app/data",
    "AION_STORAGE_LOCAL_ROOT": "/app/data",
    "AION_PROFILING_JSONL_DIR": "/app/data/profiling",
    "AION_PUBLIC_API_URL": "http://localhost/api",
    "AION_FASTAPI_URL": "http://backend:8001",
    "AION_ADMIN_UI_URL": "http://admin-ui:3870",
    "AION_AGENT_DB_LTM_SYNC_URL": "http://backend:8001/internal/agent-db/sync-drawer",
    "NEXT_PUBLIC_AION_API_URL": "/api",
    "NEXT_PUBLIC_AION_ADMIN_UI_URL": "/admin",
    "DOMAIN": ":80",
    "CADDY_HTTP_PORT": "80",
    "CADDY_HTTPS_PORT": "443",
    "AION_CORS_ORIGINS": "*",
    "AION_MCP_REGISTRY_LOCAL_PATH": "/app/data/mcp_registry.local.yaml",
    "DOCKER_BUILDKIT": "1",
    "PYTHON_VERSION": "3.13-slim",
    "UV_VERSION": "latest",
}


def _public_api_url_from_caddy(state: Dict[str, str]) -> str:
    """URL browser-side coerente con DOMAIN e porte host Caddy."""
    domain = (state.get("DOMAIN") or ":80").strip()
    http_port = (state.get("CADDY_HTTP_PORT") or "80").strip()
    https_port = (state.get("CADDY_HTTPS_PORT") or "443").strip()
    if domain and not domain.startswith(":"):
        if https_port and https_port != "443":
            return f"https://{domain}:{https_port}/api"
        return f"https://{domain}/api"
    if http_port == "80":
        return "http://localhost/api"
    return f"http://localhost:{http_port}/api"


def _apply_docker_defaults(state: Dict[str, str]) -> None:
    """Sovrascrive i valori che NON funzionerebbero dentro al network bridge Docker.

    Chiamato all'inizio del wizard quando l'utente sceglie target=docker; cosi'
    le domande successive (URL backend, Redis, ecc.) gli mostreranno default
    coerenti col `docker-compose.yml` (service DNS interno + Caddy same-origin).
    """
    for k, v in _DOCKER_DEFAULTS.items():
        current = state.get(k, "")
        # Sovrascrivi se vuoto o se contiene 'localhost'/'127.0.0.1' (sicuro reset)
        if not current or "localhost" in current or "127.0.0.1" in current or current == "data":
            state[k] = v


def _wizard_core(state: Dict[str, str]) -> Dict[str, str]:
    """Domande comuni a semplice e avanzata."""
    print("\n=== Target deploy ===\n")
    target = _prompt_choice(
        "Dove gireranno backend e chat-ui (local = python+npm sulla macchina, docker = compose)?",
        ["local", "docker"],
        state.get("AION_DEPLOY_TARGET", "local"),
    )
    state["AION_DEPLOY_TARGET"] = target  # var interna: NON scritta nel .env (non e' in .env.example)
    if target == "docker":
        _apply_docker_defaults(state)
        print(
            "  → Default Docker applicati: AION_REDIS_URL=redis://redis:6379/0, "
            "AION_DATA_DIR=/app/data, Caddy CADDY_HTTP_PORT=80 / CADDY_HTTPS_PORT=443, "
            "same-origin via Caddy (/api, /admin).\n"
            "  → Se 80/443 sono occupate sul host, imposta CADDY_HTTP_PORT/CADDY_HTTPS_PORT "
            "nel .env (es. 8066/44366) e allinea AION_PUBLIC_API_URL.\n"
            "  → Per TLS automatico Let's Encrypt imposta DOMAIN=<dominio> e "
            "LETS_ENCRYPT_EMAIL=<email> manualmente nel .env dopo il setup.\n"
            "  → Build backend: DOCKER_BUILDKIT=1, PYTHON_VERSION=3.13-slim, UV_VERSION=latest "
            "(vedi sezione DEPLOY DOCKER in .env.example).\n"
        )

    print("\n=== LLM e API ===\n")
    state["AION_API_URL"] = _prompt_str(
        "URL base LLM (OpenAI-compat, es. http://host:8000/qwen3/v1)",
        state.get("AION_API_URL", ""),
        help_text="Endpoint chat Haystack — non l’URL del backend FastAPI AION",
    )
    state["AION_MODEL"] = _prompt_str("Nome modello (AION_MODEL)", state.get("AION_MODEL", ""))
    state["AION_LLM_API_KEY"] = _prompt_str(
        "Token / API key verso il LLM (AION_LLM_API_KEY)",
        state.get("AION_LLM_API_KEY", "placeholder-token"),
        secret=True,
    )

    port = _prompt_str("Porta API FastAPI (AION_API_PORT)", state.get("AION_API_PORT", "8001"))
    state["AION_API_PORT"] = port
    base = f"http://localhost:{port}"
    state["AION_FASTAPI_URL"] = _prompt_str(
        "URL backend AION per client interni (AION_FASTAPI_URL)",
        state.get("AION_FASTAPI_URL", base),
        help_text="Usato da chat-ui (SSR). In Docker: http://backend:8001",
    )
    state["AION_PUBLIC_API_URL"] = _prompt_str(
        "URL pubblico per download (AION_PUBLIC_API_URL)",
        state.get("AION_PUBLIC_API_URL", state["AION_FASTAPI_URL"]),
    )

    print("\n=== Login chat (chat-ui) ===\n")
    print(
        "  Gli utenti sono nella tabella `users` del DB unificato (src/chat_auth.py).\n"
        "  Variabili: AION_CHAT_PASSWORD_AUTH, AION_CHAT_AUTH_SECRET.\n"
        "  Legacy AION_CHAINLIT_* viene migrato da upgrade_core.py.\n"
    )
    if _prompt_yesno("Abilitare login con password (AION_CHAT_PASSWORD_AUTH)?", False):
        state["AION_CHAT_PASSWORD_AUTH"] = "1"
        if not state.get("AION_CHAT_AUTH_SECRET"):
            state["AION_CHAT_AUTH_SECRET"] = _chat_auth_secret()
            print(f"  → AION_CHAT_AUTH_SECRET impostato ({len(state['AION_CHAT_AUTH_SECRET'])} caratteri).")
        elif _prompt_yesno("Rigenerare AION_CHAT_AUTH_SECRET?", False):
            state["AION_CHAT_AUTH_SECRET"] = _chat_auth_secret()
        print(
            "  → Dopo la scrittura del .env verrà chiesto username/password per creare il primo utente\n"
            "    (salvo setup con -y: imposta AION_SETUP_CHAT_* in .env o usa `POST /admin/users` o l’Admin UI).\n"
            "    Hash manuale (inserimento SQL): python -m src.chat_auth hash"
        )
    else:
        state["AION_CHAT_PASSWORD_AUTH"] = "0"

    print("\n=== Reasoning (default se il client non invia il campo) ===\n")
    eff_default = state.get("AION_DEFAULT_REASONING_EFFORT", "").strip().lower()
    if eff_default not in ("min", "medium", "max"):
        eff_default = "medium"
    state["AION_DEFAULT_REASONING_EFFORT"] = _prompt_choice(
        "Livello default (AION_DEFAULT_REASONING_EFFORT):",
        ["min", "medium", "max"],
        eff_default,
    )

    print("\n=== Modalità Agente Default ===\n")
    mode_default = state.get("AION_DEFAULT_AGENT_MODE", "").strip().lower()
    if mode_default not in ("normal", "plan", "ask", "debug"):
        mode_default = "normal"
    state["AION_DEFAULT_AGENT_MODE"] = _prompt_choice(
        "Modalità agente di default (AION_DEFAULT_AGENT_MODE):",
        ["normal", "plan", "ask", "debug"],
        mode_default,
    )

    print("\n=== Memoria (LTM MemPalace) ===\n")
    if _prompt_yesno("Abilitare retrieval ed estrazione LTM (AION_LTM_RETRIEVAL / AION_LTM_EXTRACT)?", state.get("AION_LTM_RETRIEVAL", "1") == "1"):
        state["AION_LTM_RETRIEVAL"] = "1"
        state["AION_LTM_EXTRACT"] = "1"
    else:
        state["AION_LTM_RETRIEVAL"] = "0"
        state["AION_LTM_EXTRACT"] = "0"

    print("\n=== Query memory / embeddings ===\n")
    provider_default = state.get("AION_EMBEDDINGS_PROVIDER", "openai").strip().lower()
    if provider_default not in ("openai", "google"):
        provider_default = "openai"
    provider = _prompt_choice(
        "Provider embeddings (AION_EMBEDDINGS_PROVIDER):",
        ["openai", "google"],
        provider_default,
    )
    state["AION_EMBEDDINGS_PROVIDER"] = provider

    default_model = state.get("AION_EMBEDDING_MODEL", "")
    default_url = state.get("AION_EMBEDDING_URL", "")

    if provider == "google":
        if not default_model or default_model == "qwen3-embedding":
            default_model = "models/gemini-embedding-001"
        if not default_url or "embedding/v1" in default_url or "localhost" in default_url:
            default_url = f"https://generativelanguage.googleapis.com/v1beta/{default_model}:embedContent"
    else:
        if not default_model or "gemini" in default_model:
            default_model = "qwen3-embedding"
        if not default_url or "googleapis.com" in default_url:
            default_url = "http://localhost:11434/v1/embeddings"

    state["AION_EMBEDDING_URL"] = _prompt_str(
        "URL servizio embeddings (AION_EMBEDDING_URL)",
        default_url,
    )
    state["AION_EMBEDDING_MODEL"] = _prompt_str(
        "Modello embeddings (AION_EMBEDDING_MODEL)",
        default_model,
    )
    state["AION_EMBEDDINGS_API_KEY"] = _prompt_str(
        "Token / API key per embeddings (AION_EMBEDDINGS_API_KEY, vuoto = nessuno)",
        state.get("AION_EMBEDDINGS_API_KEY", ""),
        secret=True,
    )

    return state


def run_simple(state: Dict[str, str]) -> Dict[str, str]:
    print("\n=== Setup semplice ===\n")
    print("Impostazioni principali; il resto resta come in .env.example o nel .env attuale.\n")
    return _wizard_core(state)


def run_advanced(state: Dict[str, str]) -> Dict[str, str]:
    print("\n=== Setup avanzato ===\n")
    print("Stesse domande della modalità semplice, poi opzioni aggiuntive.\n")
    state = _wizard_core(state)

    print("\n--- Rete e timeout API ---\n")
    state["AION_API_HOST"] = _prompt_str("Host bind API (AION_API_HOST)", state.get("AION_API_HOST", "0.0.0.0"))
    state["AION_LLM_TIMEOUT"] = _prompt_str("Timeout richieste LLM (secondi)", state.get("AION_LLM_TIMEOUT", "120"))
    state["AION_CHAT_MAX_TOKENS"] = _prompt_str("Max token risposta chat", state.get("AION_CHAT_MAX_TOKENS", "8192"))
    state["AION_AGENT_TURN_TIMEOUT"] = _prompt_str(
        "Timeout massimo turno agente (secondi)", state.get("AION_AGENT_TURN_TIMEOUT", "600")
    )

    print("\n--- Thinking token budget (vLLM Qwen3) ---\n")
    if _prompt_yesno("Impostare AION_THINKING_TOKEN_BUDGET (extra_body thinking)?", bool(state.get("AION_THINKING_TOKEN_BUDGET", "").strip())):
        state["AION_THINKING_TOKEN_BUDGET"] = _prompt_str("Budget intero (globale)", state.get("AION_THINKING_TOKEN_BUDGET", "2048"))
    else:
        state["AION_THINKING_TOKEN_BUDGET"] = ""

    if _prompt_yesno("Configurare budget specifici per effort (medium/max)?", bool(state.get("AION_THINKING_TOKEN_BUDGET_MEDIUM", "") or state.get("AION_THINKING_TOKEN_BUDGET_MAX", ""))):
        state["AION_THINKING_TOKEN_BUDGET_MEDIUM"] = _prompt_str("Budget per effort medium (token)", state.get("AION_THINKING_TOKEN_BUDGET_MEDIUM", "1024"))
        state["AION_THINKING_TOKEN_BUDGET_MAX"] = _prompt_str("Budget per effort max (token)", state.get("AION_THINKING_TOKEN_BUDGET_MAX", "2048"))
    else:
        state["AION_THINKING_TOKEN_BUDGET_MEDIUM"] = ""
        state["AION_THINKING_TOKEN_BUDGET_MAX"] = ""

    print("\n--- STM ---\n")
    state["AION_STM_MAX_TURNS"] = _prompt_str("Max turni STM", state.get("AION_STM_MAX_TURNS", "10"))
    state["AION_STM_CONSOLIDATE_EVERY"] = _prompt_str(
        "Consolidazione LTM ogni N messaggi utente", state.get("AION_STM_CONSOLIDATE_EVERY", "10")
    )

    print("\n--- LTM (dettaglio) ---\n")
    state["AION_LTM_AGENT_NAME"] = _prompt_str("Nome agente LTM", state.get("AION_LTM_AGENT_NAME", "AION"))
    state["AION_LTM_CONTEXT_MAX_CHARS"] = _prompt_str(
        "Max caratteri contesto LTM", state.get("AION_LTM_CONTEXT_MAX_CHARS", "12000")
    )

    print("\n--- OCR MCP ---\n")
    state["AION_OCR_BASE_URL"] = _prompt_str("AION_OCR_BASE_URL", state.get("AION_OCR_BASE_URL", ""))
    state["AION_OCR_API_KEY"] = _prompt_str("AION_OCR_API_KEY", state.get("AION_OCR_API_KEY", "EMPTY"), secret=True)

    print("\n--- Ricerca web (tool nativi, opzionale) ---\n")
    if _prompt_yesno("Configurare ricerca web (Tavily / Brave / SearXNG)?", False):
        state["AION_NATIVE_TOOL_REGISTRY_PATH"] = _prompt_str(
            "Registry tool nativi (AION_NATIVE_TOOL_REGISTRY_PATH)",
            state.get("AION_NATIVE_TOOL_REGISTRY_PATH", "config/native_tool_registry.yaml"),
        )
        state["AION_WEB_SEARCH_TAVILY_ENABLED"] = (
            "1" if _prompt_yesno("Abilitare Tavily (AION_WEB_SEARCH_TAVILY_ENABLED)?", False) else "0"
        )
        if state["AION_WEB_SEARCH_TAVILY_ENABLED"] == "1":
            state["AION_TAVILY_API_KEY"] = _prompt_str(
                "AION_TAVILY_API_KEY", state.get("AION_TAVILY_API_KEY", ""), secret=True
            )
        state["AION_WEB_SEARCH_BRAVE_ENABLED"] = (
            "1" if _prompt_yesno("Abilitare Brave Search API?", False) else "0"
        )
        if state["AION_WEB_SEARCH_BRAVE_ENABLED"] == "1":
            state["AION_BRAVE_SEARCH_API_KEY"] = _prompt_str(
                "AION_BRAVE_SEARCH_API_KEY", state.get("AION_BRAVE_SEARCH_API_KEY", ""), secret=True
            )
        state["AION_WEB_SEARCH_SEARXNG_ENABLED"] = (
            "1" if _prompt_yesno("Abilitare SearXNG (istanza propria)?", False) else "0"
        )
        if state["AION_WEB_SEARCH_SEARXNG_ENABLED"] == "1":
            state["AION_SEARXNG_BASE_URL"] = _prompt_str(
                "AION_SEARXNG_BASE_URL (senza slash finale)", state.get("AION_SEARXNG_BASE_URL", "")
            )
        state["AION_WEB_SEARCH_DEFAULT_PROVIDER"] = _prompt_str(
            "Provider default (tavily|brave|searxng)",
            state.get("AION_WEB_SEARCH_DEFAULT_PROVIDER", "tavily"),
        )
        state["AION_WEB_SEARCH_FALLBACK_ORDER"] = _prompt_str(
            "Fallback CSV (es. brave,searxng)", state.get("AION_WEB_SEARCH_FALLBACK_ORDER", "brave,searxng")
        )
        state["AION_WEB_SEARCH_MAX_RESULTS"] = _prompt_str(
            "Max risultati web_search (1–20, AION_WEB_SEARCH_MAX_RESULTS)",
            state.get("AION_WEB_SEARCH_MAX_RESULTS", "8"),
        )
        state["AION_WEB_SEARCH_TIMEOUT_SEC"] = _prompt_str(
            "Timeout ricerca web in secondi (AION_WEB_SEARCH_TIMEOUT_SEC)",
            state.get("AION_WEB_SEARCH_TIMEOUT_SEC", "30"),
        )
        print("\n  Allowlist organizzativa e governance (docs/configuration/web-search-and-fetch.md)\n")
        state["AION_WEB_SEARCH_ALLOWED_HOSTS"] = _prompt_str(
            "CSV host soffitto organizzazione (vuoto = off, AION_WEB_SEARCH_ALLOWED_HOSTS)",
            state.get("AION_WEB_SEARCH_ALLOWED_HOSTS", ""),
            help_text="Esempio: docs.python.org,github.com,*.wikipedia.org — effetto pieno con enforce=1 sotto",
        )
        state["AION_WEB_SEARCH_ENFORCE_GLOBAL_ALLOWLIST"] = (
            "1"
            if _prompt_yesno(
                "Applicare sempre quell'allowlist a web_search / web_fetch_page (AION_WEB_SEARCH_ENFORCE_GLOBAL_ALLOWLIST)?",
                state.get("AION_WEB_SEARCH_ENFORCE_GLOBAL_ALLOWLIST", "0") == "1",
            )
            else "0"
        )
        state["AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN"] = (
            "1"
            if _prompt_yesno(
                "Disabilitare web_search finché il client non invia web_search_enabled=true (AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN)?",
                state.get("AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN", "0") == "1",
            )
            else "0"
        )
        if _prompt_yesno("Impostare regex opzionale su URL per web_fetch_page (AION_WEB_FETCH_ALLOWLIST_REGEX)?", bool(state.get("AION_WEB_FETCH_ALLOWLIST_REGEX", "").strip())):
            state["AION_WEB_FETCH_ALLOWLIST_REGEX"] = _prompt_str(
                "Regex su URL completo", state.get("AION_WEB_FETCH_ALLOWLIST_REGEX", "")
            )
        else:
            state["AION_WEB_FETCH_ALLOWLIST_REGEX"] = state.get("AION_WEB_FETCH_ALLOWLIST_REGEX", "")

    print("\n--- MCP ---\n")
    state["AION_MCP_POOL"] = "1" if _prompt_yesno("Pool stdio MCP persistente (AION_MCP_POOL)?", state.get("AION_MCP_POOL", "1") == "1") else "0"
    state["AION_MCP_USER_POOL"] = "1" if _prompt_yesno(
        "Pool MCP condiviso per utente tra chat (AION_MCP_USER_POOL)?",
        state.get("AION_MCP_USER_POOL", "1") == "1",
    ) else "0"
    state["AION_MCP_STARTUP_WARM"] = "1" if _prompt_yesno(
        "Pre-avvio MCP al boot API (AION_MCP_STARTUP_WARM)?",
        state.get("AION_MCP_STARTUP_WARM", "1") == "1",
    ) else "0"
    if state.get("AION_MCP_STARTUP_WARM") == "1":
        state["AION_MCP_STARTUP_WARM_PROFILES"] = _prompt_str(
            "Profili per warm boot (CSV slug, o * per tutti)",
            state.get("AION_MCP_STARTUP_WARM_PROFILES", "aion_std,generic_assistant"),
        )
    state["AION_MCP_REGISTRY_PATH"] = _prompt_str(
        "Registry MCP (AION_MCP_REGISTRY_PATH)", state.get("AION_MCP_REGISTRY_PATH", "config/mcp_registry.yaml")
    )


    if _prompt_yesno("Definire overlay AION_MCP_REGISTRY_LOCAL_PATH?", bool(state.get("AION_MCP_REGISTRY_LOCAL_PATH", "").strip())):
        state["AION_MCP_REGISTRY_LOCAL_PATH"] = _prompt_str(
            "Percorso file locale", state.get("AION_MCP_REGISTRY_LOCAL_PATH", "config/mcp_registry.local.yaml")
        )
    else:
        state["AION_MCP_REGISTRY_LOCAL_PATH"] = ""

    print("\n--- MCP per-user isolation (enterprise) ---\n")
    print(
        "  Isolamento credenziali e HOME per utente in deployment multi-tenant.\n"
        "  Documentazione: docs/mcp/user-isolation-and-credentials.md\n"
    )
    if _prompt_yesno("Abilitare store credenziali per-utente (AION_MCP_USER_CREDENTIALS)?", state.get("AION_MCP_USER_CREDENTIALS", "0") == "1"):
        state["AION_MCP_USER_CREDENTIALS"] = "1"
        if not state.get("AION_CREDENTIAL_ENCRYPTION_KEY", "").strip():
            import secrets as _sec
            state["AION_CREDENTIAL_ENCRYPTION_KEY"] = _sec.token_hex(32)
            print(f"  → AION_CREDENTIAL_ENCRYPTION_KEY generata (64 caratteri hex). Conservare in un vault aziendale.")
        elif _prompt_yesno("Rigenerare AION_CREDENTIAL_ENCRYPTION_KEY? (ATTENZIONE: invalida credenziali esistenti)", False):
            import secrets as _sec
            state["AION_CREDENTIAL_ENCRYPTION_KEY"] = _sec.token_hex(32)
            print(f"  → Nuova AION_CREDENTIAL_ENCRYPTION_KEY generata.")
        print(
            "  → Gli utenti potranno configurare credenziali personali in chat-ui → Le mie integrazioni.\n"
            "    L'admin gestisce le policy in Admin UI → MCP Hub."
        )
    else:
        state["AION_MCP_USER_CREDENTIALS"] = "0"
    state["AION_MCP_USER_HOME_ISOLATION"] = "1" if _prompt_yesno(
        "Abilitare isolamento HOME/XDG per processo MCP (AION_MCP_USER_HOME_ISOLATION)?",
        state.get("AION_MCP_USER_HOME_ISOLATION", "1") == "1",
    ) else "0"

    print("\n--- Agent DB (MCP agent_db) ---\n")
    state["AION_AGENT_DB_ROOT"] = _prompt_str(
        "Directory SQLite Agent DB (AION_AGENT_DB_ROOT)", state.get("AION_AGENT_DB_ROOT", "data/agent_dbs")
    )
    state["AION_AGENT_DB_LTM_SYNC_THRESHOLD"] = _prompt_str(
        "Soglia righe insert per sync LTM (AION_AGENT_DB_LTM_SYNC_THRESHOLD)",
        state.get("AION_AGENT_DB_LTM_SYNC_THRESHOLD", "10"),
    )
    port_hint = state.get("AION_API_PORT", "") or "8001"
    sync_hint = f"http://localhost:{port_hint}/internal/agent-db/sync-drawer"
    print(f"  Esempio sync URL: {sync_hint}")
    state["AION_AGENT_DB_LTM_SYNC_URL"] = _prompt_str(
        "URL sync drawer verso API (vuoto = off; AION_AGENT_DB_LTM_SYNC_URL)",
        state.get("AION_AGENT_DB_LTM_SYNC_URL", ""),
    )
    state["AION_AGENT_DB_INTERNAL_SECRET"] = _prompt_str(
        "Secret condiviso API + MCP (AION_AGENT_DB_INTERNAL_SECRET)",
        state.get("AION_AGENT_DB_INTERNAL_SECRET", ""),
        secret=True,
    )
    state["AION_AGENT_DB_LTM_HTTP_TIMEOUT"] = _prompt_str(
        "Timeout HTTP sync secondi (AION_AGENT_DB_LTM_HTTP_TIMEOUT)",
        state.get("AION_AGENT_DB_LTM_HTTP_TIMEOUT", "8"),
    )
    state["AION_AGENT_DB_MAX_SIZE_MB"] = _prompt_str(
        "Max dimensione DB per utente in MB (AION_AGENT_DB_MAX_SIZE_MB)",
        state.get("AION_AGENT_DB_MAX_SIZE_MB", "2048"),
    )
    state["AION_AGENT_DB_MAX_TABLES_PER_USER"] = _prompt_str(
        "Max tabelle per utente (AION_AGENT_DB_MAX_TABLES_PER_USER)",
        state.get("AION_AGENT_DB_MAX_TABLES_PER_USER", "50"),
    )
    state["AION_AGENT_DB_MAX_ROWS_PER_TABLE"] = _prompt_str(
        "Max righe per tabella (AION_AGENT_DB_MAX_ROWS_PER_TABLE)",
        state.get("AION_AGENT_DB_MAX_ROWS_PER_TABLE", "500000"),
    )
    state["AION_AGENT_DB_DATE_LOCALE"] = _prompt_str(
        "Locale date (AION_AGENT_DB_DATE_LOCALE)",
        state.get("AION_AGENT_DB_DATE_LOCALE", "it_IT"),
    )
    state["AION_AGENT_DB_DECIMAL_LOCALE"] = _prompt_str(
        "Locale decimali [IT/US] (AION_AGENT_DB_DECIMAL_LOCALE)",
        state.get("AION_AGENT_DB_DECIMAL_LOCALE", "IT"),
    )
    state["AION_AGENT_DB_BACKUP_ON_DROP"] = (
        "1"
        if _prompt_yesno(
            "Abilitare backup prima del DROP fisico (AION_AGENT_DB_BACKUP_ON_DROP)?",
            state.get("AION_AGENT_DB_BACKUP_ON_DROP", "1") == "1",
        )
        else "0"
    )
    state["AION_AGENT_DB_QUERY_TIMEOUT_MS"] = _prompt_str(
        "Timeout query SELECT in ms (AION_AGENT_DB_QUERY_TIMEOUT_MS)",
        state.get("AION_AGENT_DB_QUERY_TIMEOUT_MS", "5000"),
    )
    state["AION_AGENT_DB_MAX_EXPORT_ROWS"] = _prompt_str(
        "Max righe export (AION_AGENT_DB_MAX_EXPORT_ROWS)",
        state.get("AION_AGENT_DB_MAX_EXPORT_ROWS", "100000"),
    )

    print("\n--- DB unificato / Redis ---\n")
    state["AION_DB_URL"] = _prompt_str("AION_DB_URL", state.get("AION_DB_URL", "sqlite+aiosqlite:///data/aion.db"))
    state["AION_UNIFIED_DB"] = "1" if _prompt_yesno("AION_UNIFIED_DB?", state.get("AION_UNIFIED_DB", "1") == "1") else "0"
    if _prompt_yesno("Impostare AION_REDIS_URL?", bool(state.get("AION_REDIS_URL", "").strip())):
        state["AION_REDIS_URL"] = _prompt_str("AION_REDIS_URL", state.get("AION_REDIS_URL", "redis://127.0.0.1:6379/0"))
        state["AION_REDIS_FALLBACK_LOCAL"] = state.get("AION_REDIS_FALLBACK_LOCAL", "1")
    else:
        state["AION_REDIS_URL"] = ""

    print("\n--- Storage (S3 / Local) ---\n")
    state["AION_STORAGE_BACKEND"] = _prompt_choice(
        "Backend storage (AION_STORAGE_BACKEND):",
        ["local", "s3"],
        state.get("AION_STORAGE_BACKEND", "local")
    )
    if state["AION_STORAGE_BACKEND"] == "s3":
        state["AION_STORAGE_S3_BUCKET"] = _prompt_str("S3 Bucket", state.get("AION_STORAGE_S3_BUCKET", "aion-sessions"))
        state["AION_STORAGE_S3_REGION"] = _prompt_str("S3 Region", state.get("AION_STORAGE_S3_REGION", "us-east-1"))
        state["AION_STORAGE_S3_ENDPOINT_URL"] = _prompt_str("S3 Endpoint URL (vuoto per AWS)", state.get("AION_STORAGE_S3_ENDPOINT_URL", ""))
        state["AWS_ACCESS_KEY_ID"] = _prompt_str("AWS Access Key ID", state.get("AWS_ACCESS_KEY_ID", ""), secret=True)
        state["AWS_SECRET_ACCESS_KEY"] = _prompt_str("AWS Secret Access Key", state.get("AWS_SECRET_ACCESS_KEY", ""), secret=True)
    else:
        state["AION_STORAGE_LOCAL_ROOT"] = _prompt_str("Cartella locale (AION_STORAGE_LOCAL_ROOT)", state.get("AION_STORAGE_LOCAL_ROOT", "data"))

    print("\n--- Sicurezza e plugin ---\n")
    state["AION_PII_REDACT"] = "1" if _prompt_yesno("AION_PII_REDACT?", state.get("AION_PII_REDACT", "1") == "1") else "0"
    state["AION_PLUGINS_ENABLED"] = "1" if _prompt_yesno("AION_PLUGINS_ENABLED?", state.get("AION_PLUGINS_ENABLED", "1") == "1") else "0"
    state["AION_APPROVAL_ENABLED"] = "1" if _prompt_yesno("AION_APPROVAL_ENABLED?", state.get("AION_APPROVAL_ENABLED", "1") == "1") else "0"

    print("\n--- Context compressor ---\n")
    state["AION_CONTEXT_COMPRESS_ENABLED"] = (
        "1" if _prompt_yesno("AION_CONTEXT_COMPRESS_ENABLED?", state.get("AION_CONTEXT_COMPRESS_ENABLED", "1") == "1") else "0"
    )
    state["AION_CONTEXT_COMPRESS_THRESHOLD"] = _prompt_str(
        "Soglia (0–1)", state.get("AION_CONTEXT_COMPRESS_THRESHOLD", "0.5")
    )
    state["AION_MODEL_MAX_CONTEXT"] = _prompt_str(
        "Limite contesto modello (token)", state.get("AION_MODEL_MAX_CONTEXT", "131072")
    )
    state["AION_CONTEXT_COMPRESS_MODEL_WINDOW"] = state["AION_MODEL_MAX_CONTEXT"]
    state["AION_CONTEXT_COMPRESS_KEEP_LAST"] = _prompt_str(
        "Messaggi recenti da non comprimere", state.get("AION_CONTEXT_COMPRESS_KEEP_LAST", "6")
    )
    state["AION_CONTEXT_COMPRESS_RESERVE_OUTPUT"] = (
        "1"
        if _prompt_yesno(
            "Riservare AION_CHAT_MAX_TOKENS nel budget (consigliato)?",
            state.get("AION_CONTEXT_COMPRESS_RESERVE_OUTPUT", "1") == "1",
        )
        else "0"
    )

    print("\n--- Learning (skill distill, patch, nudge) ---\n")
    state["AION_SKILL_DISTILL_ENABLED"] = (
        "1" if _prompt_yesno("Abilitare AION_SKILL_DISTILL_ENABLED?", state.get("AION_SKILL_DISTILL_ENABLED", "0") == "1") else "0"
    )
    print("  NOTA: L'abilitazione alla scrittura/cancellazione dinamica di skill (AION_SKILL_WRITE_ENABLED)")
    print("        è gestita direttamente a livello di registry MCP in config/mcp_registry.yaml")
    print("        sotto la voce 'skills_hub'.")
    state["AION_SKILL_PATCH_ENABLED"] = (
        "1" if _prompt_yesno("Abilitare AION_SKILL_PATCH_ENABLED?", state.get("AION_SKILL_PATCH_ENABLED", "0") == "1") else "0"
    )
    state["AION_NUDGE_ENABLED"] = (
        "1" if _prompt_yesno("Abilitare AION_NUDGE_ENABLED?", state.get("AION_NUDGE_ENABLED", "0") == "1") else "0"
    )

    print("\n--- Opzionale: API key bootstrap /v1 ---\n")
    if _prompt_yesno("Impostare AION_API_KEY_BOOTSTRAP (solo dev)?", bool(state.get("AION_API_KEY_BOOTSTRAP", "").strip())):
        if _prompt_yesno("Generare valore casuale?", not bool(state.get("AION_API_KEY_BOOTSTRAP", "").strip())):
            state["AION_API_KEY_BOOTSTRAP"] = f"aion_dev_{secrets.token_urlsafe(24)}"
            print("  → Salvata in .env; non committare.")
        else:
            state["AION_API_KEY_BOOTSTRAP"] = _prompt_str("Valore", state.get("AION_API_KEY_BOOTSTRAP", ""), secret=True)
    else:
        state["AION_API_KEY_BOOTSTRAP"] = ""

    print("\n--- Observability / Telemetry ---\n")
    state["AION_ENV"] = _prompt_choice(
        "Etichetta ambiente (AION_ENV):",
        ["dev", "staging", "prod"],
        state.get("AION_ENV", "dev"),
    )
    state["AION_LOG_FORMAT"] = _prompt_choice(
        "Formato log (AION_LOG_FORMAT):",
        ["json", "text"],
        state.get("AION_LOG_FORMAT", "json"),
    )
    if _prompt_yesno(
        "Abilitare OpenTelemetry tracing (AION_OTEL_ENABLED)?",
        state.get("AION_OTEL_ENABLED", "0") == "1",
    ):
        state["AION_OTEL_ENABLED"] = "1"
        state["AION_OTEL_ENDPOINT"] = _prompt_str(
            "OTel collector endpoint (AION_OTEL_ENDPOINT)",
            state.get("AION_OTEL_ENDPOINT", "http://localhost:4317"),
        )
        state["AION_OTEL_PROTOCOL"] = _prompt_choice(
            "Protocollo OTel (AION_OTEL_PROTOCOL):",
            ["grpc", "http/protobuf"],
            state.get("AION_OTEL_PROTOCOL", "grpc"),
        )
        state["AION_OTEL_SERVICE_NAME"] = _prompt_str(
            "Service name OTel (AION_OTEL_SERVICE_NAME)",
            state.get("AION_OTEL_SERVICE_NAME", "aion-agent"),
        )
    else:
        state["AION_OTEL_ENABLED"] = "0"
    state["AION_METRICS_ENABLED"] = (
        "1" if _prompt_yesno("Esporre /metrics Prometheus (AION_METRICS_ENABLED)?",
                             state.get("AION_METRICS_ENABLED", "1") == "1") else "0"
    )

    print("\n--- Docker deploy (opzionale; solo se userai docker-compose.yml) ---\n")
    if _prompt_yesno(
        "Configurare ora le variabili Docker (DOMAIN, Caddy, PYTHON_VERSION/UV_VERSION, build args frontend)?",
        bool(state.get("DOMAIN", "").strip()),
    ):
        state["DOMAIN"] = _prompt_str(
            "Dominio pubblico cliente (DOMAIN; es. cliente.example.com, ':80' per HTTP dev)",
            state.get("DOMAIN", ""),
        )
        state["LETS_ENCRYPT_EMAIL"] = _prompt_str(
            "Email contatto Let's Encrypt (LETS_ENCRYPT_EMAIL)",
            state.get("LETS_ENCRYPT_EMAIL", "ops@aion-asa.com"),
        )
        custom_ports = (
            state.get("CADDY_HTTP_PORT", "80") != "80"
            or state.get("CADDY_HTTPS_PORT", "443") != "443"
        )
        if _prompt_yesno(
            "Usare porte host diverse da 80/443 per Caddy (es. 8066/44366 se già occupate)?",
            custom_ports,
        ):
            state["CADDY_HTTP_PORT"] = _prompt_str(
                "Porta HTTP host (CADDY_HTTP_PORT)",
                state.get("CADDY_HTTP_PORT", "80"),
            )
            state["CADDY_HTTPS_PORT"] = _prompt_str(
                "Porta HTTPS host (CADDY_HTTPS_PORT)",
                state.get("CADDY_HTTPS_PORT", "443"),
            )
            if _prompt_yesno(
                "Aggiornare AION_PUBLIC_API_URL in base alle porte Caddy?",
                True,
            ):
                state["AION_PUBLIC_API_URL"] = _public_api_url_from_caddy(state)
                print(f"  → AION_PUBLIC_API_URL={state['AION_PUBLIC_API_URL']}")
        else:
            state["CADDY_HTTP_PORT"] = "80"
            state["CADDY_HTTPS_PORT"] = "443"
        if _prompt_yesno("Impostare password Redis (REDIS_PASSWORD)?",
                         bool(state.get("REDIS_PASSWORD", "").strip())):
            if _prompt_yesno("Generare valore casuale?",
                             not bool(state.get("REDIS_PASSWORD", "").strip())):
                state["REDIS_PASSWORD"] = secrets.token_urlsafe(24)
                print(f"  → REDIS_PASSWORD impostata ({len(state['REDIS_PASSWORD'])} caratteri).")
            else:
                state["REDIS_PASSWORD"] = _prompt_str(
                    "Valore", state.get("REDIS_PASSWORD", ""), secret=True
                )
        else:
            state["REDIS_PASSWORD"] = ""

        # In modalità Docker: NEXT_PUBLIC_* = /api (same-origin via Caddy reverse proxy)
        # In modalità bare-metal: NEXT_PUBLIC_AION_API_URL = http://localhost:8001
        if _prompt_yesno(
            "Build chat-ui/admin-ui per Docker (path-based via Caddy)? "
            "Sì = NEXT_PUBLIC_AION_API_URL=/api; No = http://localhost:8001",
            True,
        ):
            state["NEXT_PUBLIC_AION_API_URL"] = "/api"
            state["NEXT_PUBLIC_AION_ADMIN_UI_URL"] = "/admin"
            state["DOCUSAURUS_BASE_URL"] = "/docs/"
        else:
            state["NEXT_PUBLIC_AION_API_URL"] = state.get(
                "NEXT_PUBLIC_AION_API_URL", "http://localhost:8001"
            )
            state["NEXT_PUBLIC_AION_ADMIN_UI_URL"] = state.get(
                "NEXT_PUBLIC_AION_ADMIN_UI_URL", "http://localhost:3870"
            )
            state["DOCUSAURUS_BASE_URL"] = state.get("DOCUSAURUS_BASE_URL", "/")

        state.setdefault("DOCKER_BUILDKIT", "1")
        state.setdefault("PYTHON_VERSION", "3.13-slim")
        state.setdefault("UV_VERSION", "latest")

        # Override compose-friendly per AION_REDIS_URL/AION_DATA_DIR se ancora ai default localhost
        if state.get("AION_REDIS_URL", "").strip().startswith(("redis://localhost", "redis://127.0.0.1")):
            if _prompt_yesno(
                "Aggiornare AION_REDIS_URL a redis://redis:6379/0 (service DNS Docker)?", True
            ):
                if state["REDIS_PASSWORD"]:
                    state["AION_REDIS_URL"] = f"redis://:{state['REDIS_PASSWORD']}@redis:6379/0"
                else:
                    state["AION_REDIS_URL"] = "redis://redis:6379/0"
        if not state.get("AION_DATA_DIR") or state.get("AION_DATA_DIR") == "data":
            state["AION_DATA_DIR"] = "/app/data"

        # CORS / public URL coerenti con DOMAIN e porte Caddy
        if state["DOMAIN"] and not state["DOMAIN"].startswith(":"):
            default_pub = _public_api_url_from_caddy(state)
            https_port = (state.get("CADDY_HTTPS_PORT") or "443").strip()
            if https_port and https_port != "443":
                default_cors = f"https://{state['DOMAIN']}:{https_port}"
            else:
                default_cors = f"https://{state['DOMAIN']}"
            if state.get("AION_PUBLIC_API_URL", "") in ("", "http://localhost/api"):
                state["AION_PUBLIC_API_URL"] = default_pub
            elif not state.get("AION_PUBLIC_API_URL", "").startswith("http"):
                state["AION_PUBLIC_API_URL"] = default_pub
            if state.get("AION_CORS_ORIGINS", "*") in ("", "*"):
                state["AION_CORS_ORIGINS"] = default_cors
        elif (state.get("CADDY_HTTP_PORT") or "80") != "80":
            state["AION_PUBLIC_API_URL"] = _public_api_url_from_caddy(state)

    return state


async def _bootstrap_admin_default(
    *,
    merged_env: Dict[str, str],
    tenant_id: str,
) -> None:
    """Crea un admin di default (stile Grafana) se nessun admin esiste nel tenant.

    - Disabilitabile con ``AION_SETUP_ADMIN_BOOTSTRAP=0``.
    - Override credenziali con ``AION_SETUP_ADMIN_DEFAULT_IDENTIFIER`` /
      ``AION_SETUP_ADMIN_DEFAULT_PASSWORD``.
    - L'admin viene creato con ``must_change_password=True`` cosi' il primo
      accesso mostra il banner di cambio password (skippabile 24h).
    """
    from src.data.user_password import (
        UserAlreadyExistsError,
        admin_exists,
        create_password_user,
    )

    flag = (merged_env.get("AION_SETUP_ADMIN_BOOTSTRAP") or "1").strip().lower()
    if flag not in ("1", "true", "yes"):
        return

    if await admin_exists(tenant_id=tenant_id):
        return

    identifier = (
        merged_env.get("AION_SETUP_ADMIN_DEFAULT_IDENTIFIER") or "admin"
    ).strip() or "admin"
    password = (
        merged_env.get("AION_SETUP_ADMIN_DEFAULT_PASSWORD") or "admin"
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
        # Race con creazione manuale: nessun problema.
        return

    print(
        "\n========================================================================\n"
        f" ADMIN DI DEFAULT CREATO: identifier={identifier!r} password={password!r}\n"
        " Al primo login verra' proposto di cambiare la password (skippabile 24h).\n"
        " Disabilita con AION_SETUP_ADMIN_BOOTSTRAP=0 nel .env prima del setup.\n"
        f" (id utente DB: {uid}, tenant: {tenant_id!r})\n"
        "========================================================================\n"
    )


async def _bootstrap_chat_user_coroutine(
    *,
    interactive: bool,
    merged_env: Dict[str, str],
    chat_auth_enabled: bool,
) -> None:
    try:
        import src.aion_env  # noqa: F401
    except ImportError:
        pass

    from src.data.bootstrap import ensure_bootstrap_schema, patch_sqlite_schema_drift
    from src.data.engine import init_engine
    from src.data.migrations import run_migrations
    from src.data.user_password import UserAlreadyExistsError, create_password_user
    from src.runtime.timeline_backfill import backfill_message_timelines

    tenant_id = (merged_env.get("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"

    eng = init_engine()
    await ensure_bootstrap_schema(eng)
    run_migrations()
    await patch_sqlite_schema_drift(eng)
    try:
        n = await backfill_message_timelines()
        if n:
            print(f"  Timeline backfill: aggiornati {n} messaggi assistant.")
    except Exception as exc:
        print(f"  [warn] Timeline backfill skipped: {exc}")

    # Admin di default (sempre): il pannello /admin e' sempre protetto.
    await _bootstrap_admin_default(merged_env=merged_env, tenant_id=tenant_id)

    # Creazione utente chat: solo se il login chat e' attivo.
    if not chat_auth_enabled:
        return

    if interactive:
        print("\n=== Creazione utente login chat (tabella users del DB unificato) ===\n")
        identifier = _prompt_str("Username (identifier)", "admin")
        pw = getpass.getpass("Password chat: ")
        pw2 = getpass.getpass("Ripeti password: ")
        if pw != pw2:
            print("ERRORE: password diverse. Crea l’utente dall'Admin UI o tramite l’API POST /admin/users.")
            return
        if not pw:
            print("Password vuota. Crea l’utente dall'Admin UI o tramite l’API POST /admin/users.")
            return
    else:
        # Nuovi nomi + fallback legacy
        identifier = (
            merged_env.get("AION_SETUP_CHAT_IDENTIFIER")
            or merged_env.get("AION_SETUP_CHAINLIT_IDENTIFIER")
            or ""
        ).strip()
        pw = (
            merged_env.get("AION_SETUP_CHAT_PASSWORD")
            or merged_env.get("AION_SETUP_CHAINLIT_PASSWORD")
            or ""
        ).strip()
        if not identifier or not pw:
            print(
                "\n→ Login chat attivo: per creare un utente senza prompt interattivo, "
                "imposta nel .env AION_SETUP_CHAT_IDENTIFIER e AION_SETUP_CHAT_PASSWORD "
                "e rilancia con --import-state, oppure usa l'API POST /admin/users o l’Admin UI.\n"
                "  (Legacy alias supportati: AION_SETUP_CHAINLIT_IDENTIFIER / AION_SETUP_CHAINLIT_PASSWORD)\n"
            )
            return

    try:
        uid = await create_password_user(
            tenant_id=tenant_id,
            identifier=identifier,
            password=pw,
        )
    except UserAlreadyExistsError:
        print(f"\n→ Utente {identifier!r} già presente nel tenant {tenant_id!r}; nessuna modifica.\n")
        return

    db_url = merged_env.get("AION_DB_URL", "")
    print(
        f"\n[OK] Utente login chat creato (id={uid}, identifier={identifier!r}, tenant={tenant_id!r}).\n"
        f"  Conserva la password con cura (non viene mostrata di nuovo).\n"
        f"  DB: {db_url}\n"
    )


def _bootstrap_chat_login_after_env_write(env_path: Path, *, interactive: bool) -> None:
    merged = _parse_env_file(env_path)
    # Nuovo nome con fallback legacy.
    pwd_auth_raw = (
        merged.get("AION_CHAT_PASSWORD_AUTH")
        or merged.get("AION_CHAINLIT_PASSWORD_AUTH")
        or "0"
    )
    chat_auth = pwd_auth_raw.lower() in ("1", "true", "yes")

    # Bootstrap admin default: gira sempre a meno che esplicitamente disabilitato.
    admin_bootstrap = (merged.get("AION_SETUP_ADMIN_BOOTSTRAP") or "1").lower() in (
        "1",
        "true",
        "yes",
    )
    if not chat_auth and not admin_bootstrap:
        return

    unified = merged.get("AION_UNIFIED_DB", "1").lower() in ("1", "true", "yes")
    if not unified:
        if chat_auth:
            print(
                "\n⚠ AION_CHAT_PASSWORD_AUTH=1 ma il DB unificato non è attivo "
                "(AION_UNIFIED_DB≠1): il login usa comunque la tabella ``users`` "
                "in AION_DB_URL. Ripristina AION_UNIFIED_DB=1 oppure crea gli "
                "utenti dall’Admin UI o tramite l’API POST /admin/users.\n"
            )
        # Senza DB unificato non si puo' fare bootstrap admin automatico.
        return

    for k, v in merged.items():
        os.environ[k] = v

    try:
        asyncio.run(
            _bootstrap_chat_user_coroutine(
                interactive=interactive,
                merged_env=merged,
                chat_auth_enabled=chat_auth,
            )
        )
    except Exception as e:
        print(f"\n⚠ Bootstrap utenti fallito: {e}\n")
        print("  Ripeti manualmente tramite l'API POST /admin/users o l'Admin UI\n")


def main() -> int:
    _ver = _read_version()
    print(f"\n✨  AION Agent Setup  —  {_ver}\n")
    ap = argparse.ArgumentParser(description="Setup guidato .env per AION Agent")

    ap.add_argument("--simple", action="store_true", help="Solo impostazioni principali")
    ap.add_argument("--advanced", action="store_true", help="Setup esteso dopo il nucleo comune")
    ap.add_argument("--dry-run", action="store_true", help="Stampa anteprima senza scrivere")
    ap.add_argument("--output", type=Path, default=_REPO_ROOT / ".env", help="File output (default: .env)")
    ap.add_argument(
        "--import-state",
        type=Path,
        metavar="FILE",
        help="Applica solo le chiavi presenti in FILE (formato KEY=val) sopra .env.example + .env esistente; salta il wizard.",
    )
    ap.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Non chiedere conferma prima di scrivere il file (utile da script shell).",
    )
    args = ap.parse_args()
    env_path: Path = args.output.resolve()

    if args.import_state is not None:
        if not args.import_state.is_file():
            print(f"ERRORE: --import-state non è un file: {args.import_state}", file=sys.stderr)
            return 2
        state = _initial_state()
        for k, v in _parse_env_file(args.import_state.resolve()).items():
            state[k] = v
        managed_keys = _writable_keys()  # esclude alias legacy
        example = _parse_env_file(_EXAMPLE)
        managed = {k: state.get(k, example.get(k, "")) for k in managed_keys}
        old = _parse_env_file(env_path)
        preserved = {
            k: v for k, v in old.items()
            if k not in managed and k not in _DEPRECATED_KEYS
        }
        if args.dry_run:
            print("\n--- Anteprima (dry-run, --import-state) ---\n")
            print(_build_write_blocks(managed, preserved))
            return 0
        if env_path.is_file() and not args.yes:
            if not _prompt_yesno(f"Scrivere (chiavi da .env.example + preservazione altre) su {env_path}?", True):
                print("Annullato.")
                return 1
        _, bak = _write_env(env_path, managed, dry_run=False)
        if bak:
            print(f"\nBackup: {bak}")
        print(f"\nScritto: {env_path}")
        _bootstrap_chat_login_after_env_write(env_path, interactive=not args.yes)
        return 0

    state = _initial_state()

    if args.simple:
        state = run_simple(state)
    elif args.advanced:
        state = run_advanced(state)
    else:
        print("Modalità:\n  1) Semplice — LLM, API, login chat, reasoning, LTM, embeddings\n")
        print(
            "  2) Avanzata — come (1) + timeout, STM, OCR, MCP, ricerca web (allowlist/enforce), DB/Redis, PII, plugin, approval, "
            "compressor, skill/nudge, API key\n"
        )
        c = input("Scegli [1/2] (default 1): ").strip() or "1"
        state = run_advanced(state) if c == "2" else run_simple(state)

    managed_keys = _writable_keys()  # esclude alias legacy (_DEPRECATED_KEYS)
    example = _parse_env_file(_EXAMPLE)
    managed = {k: state.get(k, example.get(k, "")) for k in managed_keys}

    if args.dry_run:
        print("\n--- Anteprima (dry-run) ---\n")
        print(_build_write_blocks(managed, {}))
        return 0

    if env_path.is_file() and not args.yes and not _prompt_yesno(
        f"Scrivere (chiavi da .env.example + preservazione altre) su {env_path}?", True
    ):
        print("Annullato.")
        return 1

    _, bak = _write_env(env_path, managed, dry_run=False)
    if bak:
        print(f"\nBackup: {bak}")
    print(f"\nScritto: {env_path}")
    _bootstrap_chat_login_after_env_write(env_path, interactive=not args.yes)
    print("\nProssimi passi:")
    if (state.get("AION_DEPLOY_TARGET") or "").lower() == "docker":
        print("  DOCKER_BUILDKIT=1 docker compose build")
        print("  docker compose up -d")
        print("  docker compose logs -f backend")
        print("  Apri http://localhost/  (chat-ui)  |  http://localhost/admin  |  http://localhost/docs/")
    else:
        print("  # deps: upgrade-aion.sh usa uv se disponibile (come il Dockerfile backend)")
        print("  python scripts/init_unified_db.py     # idempotente: alembic + timeline backfill")
        print("  ./scripts/dev-api.sh                    # backend FastAPI :8001 (uv venv se disponibile)")
        print("  cd chat-ui && pnpm install && pnpm dev  # client primario :8003")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
