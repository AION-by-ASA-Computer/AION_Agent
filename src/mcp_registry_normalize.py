"""
Rilevamento entrypoint e patch registry post-install marketplace (git/npx).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .mcp_connector_catalog import infer_connector_id_for_registry_name, load_mcp_connector_catalog
from .mcp_manager import mcp_manager

logger = logging.getLogger("aion.mcp_registry_normalize")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _pyproject_console_scripts(dest: Path) -> List[str]:
    try:
        import tomllib

        data = tomllib.loads((dest / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = data.get("project", {}).get("scripts") or {}
        if isinstance(scripts, dict):
            return [str(k) for k in scripts if k]
    except Exception:
        pass
    return []


def _pyproject_name(dest: Path) -> str:
    try:
        import tomllib

        data = tomllib.loads((dest / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data.get("project", {}).get("name") or "").strip()
    except Exception:
        return ""


def detect_stdio_entrypoint(server_slug: str) -> Tuple[str, List[str]]:
    """
    Sceglie command/args per server sotto mcp_servers/<slug> o path in registry.
    Python (pyproject.toml): uv run --directory <clone> <script> stdio.
    Node/TS: bun/tsx/node come prima.
    """
    cfg = mcp_manager.get_server_config(server_slug) or {}
    clone = (cfg.get("aion_market_clone_path") or f"mcp_servers/{server_slug}").replace("\\", "/")
    dest = _repo_root() / clone
    if not dest.is_dir():
        dest = _repo_root() / "mcp_servers" / server_slug

    rel_dir = str(dest.relative_to(_repo_root())).replace("\\", "/") if dest.is_dir() else clone

    if (dest / "pyproject.toml").is_file():
        scripts = _pyproject_console_scripts(dest)
        script = scripts[0] if scripts else _pyproject_name(dest).replace("-", "_")
        if not script:
            script = server_slug.replace("-", "_")
        venv_bin = dest / ".venv" / "bin" / script
        if sys.platform == "win32":
            venv_bin = dest / ".venv" / "Scripts" / f"{script}.exe"
        if venv_bin.is_file():
            rel_bin = str(venv_bin.relative_to(_repo_root())).replace("\\", "/")
            return rel_bin, ["stdio"]
        if shutil.which("uv"):
            return "uv", ["run", "--directory", rel_dir, script, "stdio"]
        pkg = _pyproject_name(dest) or script.replace("_", "-")
        if shutil.which("uvx") and pkg:
            return "uvx", [f"{pkg}@latest", "stdio"]

    if (dest / "requirements.txt").is_file():
        for entry in ("server.py", "main.py", "__main__.py"):
            if (dest / entry).is_file():
                rel = str((dest / entry).relative_to(_repo_root())).replace("\\", "/")
                return "python3", [rel]

    pkg_path = dest / "package.json"
    main_ts = dest / "index.ts"
    main_js = dest / "index.js"
    build_js = dest / "build" / "index.js"

    if build_js.is_file():
        rel = str(build_js.relative_to(_repo_root())).replace("\\", "/")
        return "node", [rel]

    if main_ts.is_file():
        rel = str(main_ts.relative_to(_repo_root())).replace("\\", "/")
        if shutil.which("bun"):
            return "bun", ["run", rel]
        if shutil.which("npx"):
            return "npx", ["tsx", rel]
        return "bun", ["run", rel]

    if pkg_path.is_file():
        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}

        # 1) Campo "bin" di package.json — ha priorità su "main" e file fisici
        #    (es. {"playwright-mcp": "cli.js"} — il CLI entrypoint reale)
        bin_field = data.get("bin")
        if isinstance(bin_field, dict):
            for _bin_name, bin_path in bin_field.items():
                candidate_bin = dest / bin_path
                if candidate_bin.is_file():
                    rel = str(candidate_bin.relative_to(_repo_root())).replace("\\", "/")
                    if str(bin_path).endswith(".ts"):
                        if shutil.which("bun"):
                            return "bun", ["run", rel]
                        return "npx", ["tsx", rel]
                    return "node", [rel]
        elif isinstance(bin_field, str):
            candidate_bin = dest / bin_field
            if candidate_bin.is_file():
                rel = str(candidate_bin.relative_to(_repo_root())).replace("\\", "/")
                return "node", [rel]

        # 2) Campo "main" di package.json (es. "./dist/main.js")
        main_field = data.get("main") or "index.js"
        candidate = dest / main_field
        if candidate.is_file():
            rel = str(candidate.relative_to(_repo_root())).replace("\\", "/")
            if main_field.endswith(".ts"):
                if shutil.which("bun"):
                    return "bun", ["run", rel]
                return "npx", ["tsx", rel]
            return "node", [rel]

        # 3) File fisico index.js (fallback — solo se non c'è bin/main)
        if main_js.is_file():
            rel = str(main_js.relative_to(_repo_root())).replace("\\", "/")
            return "node", [rel]

        # Fallback: cerca src/main.ts, src/index.ts (sorgenti TypeScript)
        for src_entry in ("src/main.ts", "src/index.ts", "src/server.ts", "main.ts", "index.ts"):
            candidate_src = dest / src_entry
            if candidate_src.is_file():
                rel = str(candidate_src.relative_to(_repo_root())).replace("\\", "/")
                if shutil.which("bun"):
                    return "bun", ["run", rel]
                if shutil.which("npx"):
                    return "npx", ["tsx", rel]
                return "bun", ["run", rel]

    raise FileNotFoundError(
        f"Nessun entrypoint MCP rilevato in {rel_dir} (attesi pyproject.toml, package.json o server.py)"
    )


def _uv_sync_clone(dest: Path) -> None:
    """Pre-installa la venv del clone così il primo avvio MCP non supera il timeout handshake."""
    if not (dest / "pyproject.toml").is_file() or not shutil.which("uv"):
        return
    import subprocess

    try:
        rel = str(dest.relative_to(_repo_root())).replace("\\", "/")
        subprocess.run(
            ["uv", "sync", "--directory", rel],
            cwd=str(_repo_root()),
            check=False,
            timeout=600,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("uv sync %s skipped: %s", dest, e)


def normalize_installed_server_registry(server_slug: str) -> Dict[str, Any]:
    """Aggiorna command/args e aion_connector_id dopo install git; non forza credential_mode."""
    mcp_manager.load_registry()
    if server_slug not in mcp_manager._registry:
        return {"ok": False, "error": f"Server '{server_slug}' not in registry"}

    catalog = load_mcp_connector_catalog()
    cfg = dict(mcp_manager.get_server_config(server_slug) or {})
    install_type = cfg.get("aion_market_install") or ""

    patch: Dict[str, Any] = {}
    if not cfg.get("aion_connector_id"):
        cid = infer_connector_id_for_registry_name(server_slug, catalog)
        if cid:
            patch["aion_connector_id"] = cid

    needs_detect = install_type == "git"
    if not needs_detect and cfg.get("command") == "node":
        args_list = cfg.get("args") or []
        if args_list:
            first = str(args_list[0])
            candidate = _repo_root() / first
            if not candidate.is_file():
                needs_detect = True
    if needs_detect:
        clone = (cfg.get("aion_market_clone_path") or f"mcp_servers/{server_slug}").replace("\\", "/")
        dest = _repo_root() / clone
        if dest.is_dir():
            _uv_sync_clone(dest)
        try:
            cmd, args = detect_stdio_entrypoint(server_slug)
            patch["command"] = cmd
            patch["args"] = args
        except FileNotFoundError as e:
            logger.warning("detect_stdio_entrypoint %s: %s", server_slug, e)

    if patch:
        mcp_manager.update_server_config(server_slug, patch)
        logger.info("normalize registry %s: %s", server_slug, patch)

    return {"ok": True, "server_slug": server_slug, "patch": patch}


async def normalize_and_apply_env_after_install(server_slug: str) -> Dict[str, Any]:
    """Normalize entrypoint then apply suggested env using inferred credential_mode (no AI)."""
    from .mcp_integration_sync import apply_integration_config, build_integration_preview

    norm = normalize_installed_server_registry(server_slug)
    if not norm.get("ok"):
        return norm
    preview = build_integration_preview(server_slug)
    if not preview.get("ok"):
        return preview
    mode = preview.get("credential_mode") or "none"
    return await apply_integration_config(
        server_slug,
        credential_mode=mode,
        apply_suggested_env=mode in ("per_user", "org_shared"),
    )
