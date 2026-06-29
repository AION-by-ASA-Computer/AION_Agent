#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP_PY = ROOT / "scripts" / "setup_aion_env.py"
SYNC_CONFIG = ROOT / "scripts" / "sync_config.py"
SYNC_MCP_SERVERS = ROOT / "scripts" / "sync_mcp_servers.py"
RUNTIME_EXTRAS = ROOT / "scripts" / "runtime_extras_setup.py"
ENSURE_SKILL_PACKAGES = ROOT / "scripts" / "ensure_skill_packages.py"
PATCH_SQL_QM_CONFIG = ROOT / "scripts" / "patch_sql_query_memory_config.py"
PATCH_MEMPALACE_NAV_CONFIG = ROOT / "scripts" / "patch_mempalace_navigation_config.py"
VENV_DIR = ROOT / ".venv"
REQ = ROOT / "requirements.txt"


def _run(cmd: list[str], dry_run: bool = False) -> int:
    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return 0
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def _merge_env_local(path: Path, key: str, value: str) -> None:
    existing: dict[str, str] = {}
    order: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            if k not in existing:
                order.append(k)
            existing[k] = v
    if key not in existing:
        order.append(key)
    existing[key] = value
    out = [f"{k}={existing[k]}" for k in order]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _ensure_venv(base_python: str, dry_run: bool) -> str:
    if dry_run:
        py = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        return str(py if py.exists() else base_python)
    import importlib.util

    path = ROOT / "scripts" / "uv_runtime.py"
    spec = importlib.util.spec_from_file_location("aion_uv_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    uv_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(uv_mod)
    return uv_mod.ensure_venv(base_python, dry_run=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-platform setup orchestrator")
    ap.add_argument("--simple", action="store_true")
    ap.add_argument("--advanced", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-o", "--output", default=str(ROOT / ".env"))
    ap.add_argument("--prepare-runtime", action="store_true", help="Create/update venv + install deps")
    ap.add_argument(
        "--enable-fs-policy-dev",
        action="store_true",
        help="Copy config/fs_policy.dev.yaml -> fs_policy.yaml and set AION_FS_POLICY_PATH in .env",
    )
    ap.add_argument(
        "--skip-promo-playwright",
        action="store_true",
        help="Skip Playwright/Chromium install for promo_render MCP",
    )
    ap.add_argument("--no-sync-admin-ui", action="store_true")
    ap.add_argument("--non-interactive", action="store_true", help="Skip wizard prompts and merge defaults only")
    args = ap.parse_args()

    if not SETUP_PY.exists():
        print(f"Missing {SETUP_PY}", file=sys.stderr)
        return 2
    if not SYNC_CONFIG.exists():
        print(f"Missing {SYNC_CONFIG}", file=sys.stderr)
        return 2
    if not SYNC_MCP_SERVERS.exists():
        print(f"Missing {SYNC_MCP_SERVERS}", file=sys.stderr)
        return 2

    base_python = sys.executable or "python3"
    py_exec = base_python
    if args.prepare_runtime and not args.dry_run:
        py_exec = _ensure_venv(base_python, dry_run=False)

    # dry-run must be no side effects
    if not args.dry_run:
        if ENSURE_SKILL_PACKAGES.is_file():
            rc = _run([py_exec, str(ENSURE_SKILL_PACKAGES)])
            if rc != 0:
                print("[warn] ensure_skill_packages failed", file=sys.stderr)
        else:
            rc = _run([py_exec, str(SYNC_CONFIG)])
            if rc != 0:
                return rc
            rc = _run([py_exec, str(SYNC_MCP_SERVERS)])
            if rc != 0:
                return rc
        if RUNTIME_EXTRAS.exists():
            extras_cmd = [
                py_exec,
                str(RUNTIME_EXTRAS),
                "--env-file",
                args.output,
            ]
            if args.dry_run:
                extras_cmd.append("--dry-run")
            if args.enable_fs_policy_dev:
                extras_cmd.append("--enable-fs-policy-dev")
            if args.skip_promo_playwright:
                extras_cmd.append("--skip-promo-playwright")
            rc = _run(extras_cmd)
            if rc != 0:
                print(
                    "[warn] runtime_extras_setup exited non-zero (optional promo/fs steps)",
                    file=sys.stderr,
                )
        if PATCH_MEMPALACE_NAV_CONFIG.is_file() and not args.dry_run:
            rc = _run(
                [
                    py_exec,
                    str(PATCH_MEMPALACE_NAV_CONFIG),
                    "--force-skills",
                    "--force-profile-sync",
                ]
            )
            if rc != 0:
                print("[warn] patch_mempalace_navigation_config failed", file=sys.stderr)
        if PATCH_SQL_QM_CONFIG.is_file() and not args.dry_run:
            rc = _run([py_exec, str(PATCH_SQL_QM_CONFIG)])
            if rc != 0:
                print("[warn] patch_sql_query_memory_config failed", file=sys.stderr)

    invoke = [py_exec, str(SETUP_PY)]
    temp_import_path: Path | None = None
    if args.non_interactive:
        fd, tpath = tempfile.mkstemp(prefix="aion_setup_core_", suffix=".env")
        os.close(fd)
        temp_import_path = Path(tpath)
        temp_import_path.write_text("", encoding="utf-8")
        invoke += ["--import-state", str(temp_import_path)]
        if args.dry_run:
            invoke.append("--dry-run")
        else:
            invoke.append("-y")
    else:
        if args.simple:
            invoke.append("--simple")
        elif args.advanced:
            invoke.append("--advanced")
        if args.dry_run:
            invoke.append("--dry-run")
    invoke += ["--output", args.output]
    rc = _run(invoke, dry_run=False)
    if temp_import_path is not None and temp_import_path.exists():
        temp_import_path.unlink(missing_ok=True)
    if rc != 0:
        return rc

    if not args.dry_run and not args.no_sync_admin_ui:
        admin_ui = ROOT / "admin-ui"
        out_path = Path(args.output)
        if admin_ui.exists() and out_path.exists():
            content = out_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("NEXT_PUBLIC_AION_API_URL="):
                    ui_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if ui_url:
                        _merge_env_local(admin_ui / ".env.local", "NEXT_PUBLIC_AION_API_URL", ui_url)
                    break

    if not args.dry_run:
        out_path = Path(args.output)
        if out_path.is_file():
            try:
                import importlib.util

                up_path = ROOT / "scripts" / "upgrade_core.py"
                spec = importlib.util.spec_from_file_location("aion_upgrade_core", up_path)
                if spec and spec.loader:
                    up_mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(up_mod)
                    rep = up_mod.Report()
                    up_mod._ensure_sql_qm_env_keys(out_path, dry_run=False, report=rep)
                    up_mod._ensure_mempalace_nav_env_keys(out_path, dry_run=False, report=rep)
                    up_mod._ensure_skill_view_env_keys(out_path, dry_run=False, report=rep)
                    up_mod._ensure_agent_mode_env_keys(out_path, dry_run=False, report=rep)
                    up_mod._ensure_deep_research_env_keys(out_path, dry_run=False, report=rep)
            except Exception as exc:
                print(f"[warn] memory env defaults (SQL QM / MemPalace nav): {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
