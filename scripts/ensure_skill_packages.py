"""
Sync skill packages from config_std/ to config/ and sync MCP servers.

Called from setup_core.py and upgrade_core.py:
  1. sync_config.py (safe) then --skills-only --force → config/
  2. sync_mcp_servers.py (--force optional)

To promote local packages from config/skills/ into config_std/ (maintainer only):
  python scripts/sync_local_skill_packages_to_std.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC_CONFIG = ROOT / "scripts" / "sync_config.py"
SYNC_MCP = ROOT / "scripts" / "sync_mcp_servers.py"


def _run(cmd: list[str], dry_run: bool = False) -> int:
    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return 0
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def ensure_skill_packages(
    py_exec: str,
    *,
    dry_run: bool = False,
    force_mcp_sync: bool = False,
) -> int:
    if SYNC_CONFIG.is_file():
        rc = _run([py_exec, str(SYNC_CONFIG)], dry_run=dry_run)
        if rc != 0:
            return rc
        rc = _run(
            [py_exec, str(SYNC_CONFIG), "--skills-only", "--force"],
            dry_run=dry_run,
        )
        if rc != 0:
            print("[warn] sync_config --skills-only --force failed", file=sys.stderr)

    if SYNC_MCP.is_file():
        cmd = [py_exec, str(SYNC_MCP)]
        if force_mcp_sync:
            cmd.append("--force")
        rc = _run(cmd, dry_run=dry_run)
        if rc != 0:
            print("[warn] sync_mcp_servers failed", file=sys.stderr)

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync skill packages and MCP servers")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-mcp-sync", action="store_true")
    args = ap.parse_args()
    py = sys.executable
    return ensure_skill_packages(
        py, dry_run=args.dry_run, force_mcp_sync=args.force_mcp_sync
    )


if __name__ == "__main__":
    raise SystemExit(main())
