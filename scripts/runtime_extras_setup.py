"""
Optional runtime setup: filesystem exec policy templates + promo Playwright (MCP PNG).
Used by setup_core.py and upgrade_core.py.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_STD = ROOT / "config_std"
CONFIG = ROOT / "config"
SETUP_PROMO_SH = ROOT / "scripts" / "setup_promo_playwright.sh"

_PROMO_ENV_DEFAULTS: dict[str, str] = {
    "AION_PROMO_CAPTURE_ENABLED": "1",
}


def _parse_env_simple(path: Path) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    for raw in text.splitlines():
        s = raw.lstrip()
        if not s or s.startswith("#") or "=" not in raw:
            out.append(("", "", raw))
            continue
        key, _, val = raw.partition("=")
        out.append((key.strip(), val.strip(), raw))
    return out


def ensure_fs_policy_files(*, dry_run: bool, report) -> int:
    """Copy fs_policy templates from config_std into config/ if missing."""
    CONFIG.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in ("fs_policy.example.yaml", "fs_policy.dev.yaml"):
        src = CONFIG_STD / name
        dst = CONFIG / name
        if not src.is_file():
            report.log_warn(f"FS policy template missing: {src}")
            continue
        if dst.is_file():
            continue
        if dry_run:
            report.log_ok(f"FS policy: would copy {name} -> config/ (dry-run)")
            copied += 1
            continue
        shutil.copy2(src, dst)
        copied += 1
    if copied:
        report.log_ok(f"FS policy templates: copied {copied} file(s) to config/")
    else:
        report.log_ok("FS policy templates: already present in config/")
    return 0


def ensure_fs_policy_dev_active(env_path: Path, *, dry_run: bool, report) -> int:
    """Enable dev exec policy: config/fs_policy.yaml from dev template + .env path."""
    src = CONFIG / "fs_policy.dev.yaml"
    if not src.is_file():
        src = CONFIG_STD / "fs_policy.dev.yaml"
    dst = CONFIG / "fs_policy.yaml"
    rel_policy = "config/fs_policy.yaml"
    if not src.is_file():
        report.log_warn("fs_policy.dev.yaml not found — run sync_config first")
        return 0
    if not dry_run:
        shutil.copy2(src, dst)
    report.log_ok(f"FS policy dev: {'would activate' if dry_run else 'activated'} {rel_policy}")

    if not env_path.is_file():
        report.log_warn("FS policy dev: .env missing, skip AION_FS_POLICY_PATH")
        return 0

    entries = _parse_env_simple(env_path)
    keys = {k for k, _, _ in entries if k}
    if "AION_FS_POLICY_PATH" in keys:
        report.log_ok("FS policy dev: AION_FS_POLICY_PATH already in .env")
        return 0
    if dry_run:
        report.log_ok("FS policy dev: would append AION_FS_POLICY_PATH to .env (dry-run)")
        return 0
    block = (
        "\n# --- Filesystem exec policy (dev — append da setup/upgrade) ---\n"
        f"AION_FS_POLICY_PATH={rel_policy}\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + block,
            encoding="utf-8",
        )
    except OSError as e:
        report.log_fail(f"FS policy dev: .env write failed: {e}")
        return 3
    report.log_ok("FS policy dev: appended AION_FS_POLICY_PATH to .env")
    return 0


_WREN_ALLOWLIST_BLOCK = """    # --- Wren CLI (semantic SQL layer; skills/wren/SKILL.md) ---
    - executable: "wren"
      argv_prefix: []
"""


def _resolve_active_fs_policy_path(env_path: Path) -> Path | None:
    """Return config/fs_policy.yaml (or path from .env) when present."""
    if env_path.is_file():
        for key, val, _ in _parse_env_simple(env_path):
            if key == "AION_FS_POLICY_PATH" and val.strip():
                p = Path(val.strip())
                if not p.is_absolute():
                    p = ROOT / p
                return p
    active = CONFIG / "fs_policy.yaml"
    if active.is_file():
        return active
    return None


def ensure_fs_policy_wren_allowlist(env_path: Path, *, dry_run: bool, report) -> int:
    """Append ``wren`` to exec.allowlist on the active fs_policy file (idempotent)."""
    policy = _resolve_active_fs_policy_path(env_path)
    if policy is None or not policy.is_file():
        report.log_ok("FS policy wren: no active policy file, skip")
        return 0
    try:
        text = policy.read_text(encoding="utf-8")
    except OSError as e:
        report.log_warn(f"FS policy wren: read failed ({policy}): {e}")
        return 0
    if 'executable: "wren"' in text or "executable: wren\n" in text:
        report.log_ok("FS policy wren: already in allowlist")
        return 0
    if "allowlist:" not in text:
        report.log_warn(f"FS policy wren: no allowlist section in {policy.name}, skip")
        return 0
    if "\nlimits:" in text:
        new_text = text.replace("\nlimits:", f"\n{_WREN_ALLOWLIST_BLOCK}\nlimits:", 1)
    else:
        new_text = text.rstrip() + "\n" + _WREN_ALLOWLIST_BLOCK + "\n"
    if dry_run:
        report.log_ok(f"FS policy wren: would patch {policy.relative_to(ROOT)} (dry-run)")
        return 0
    try:
        policy.write_text(new_text, encoding="utf-8")
    except OSError as e:
        report.log_fail(f"FS policy wren: write failed ({policy}): {e}")
        return 3
    report.log_ok(f"FS policy wren: patched {policy.relative_to(ROOT)}")
    return 0


def ensure_promo_env_keys(env_path: Path, *, dry_run: bool, report) -> int:
    """Append promo capture defaults if missing (does not set FS policy path)."""
    if not env_path.is_file():
        report.log_ok("Promo env defaults: .env absent, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys = {k for k, _, _ in entries if k}
    missing = [(k, v) for k, v in _PROMO_ENV_DEFAULTS.items() if k not in keys]
    if not missing:
        report.log_ok("Promo env defaults: keys already present")
        return 0
    if dry_run:
        report.log_ok(f"Promo env defaults: would append {len(missing)} key(s) (dry-run)")
        return 0
    block = (
        "\n# --- Promo render MCP (append da setup/upgrade) ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + block,
            encoding="utf-8",
        )
    except OSError as e:
        report.log_fail(f"Promo env defaults: write failed: {e}")
        return 3
    report.log_ok(f"Promo env defaults: appended {len(missing)} key(s)")
    return 0


def setup_promo_playwright(*, dry_run: bool, report, skip: bool = False) -> int:
    """Install Playwright + Chromium for promo_render (MCP Python, not session venv)."""
    if skip:
        report.log_ok("Promo Playwright: skipped by flag")
        return 0
    if not SETUP_PROMO_SH.is_file():
        report.log_warn(f"Missing {SETUP_PROMO_SH}")
        return 0
    if dry_run:
        report.log_ok("Promo Playwright: would run setup_promo_playwright.sh (dry-run)")
        return 0
    rc = subprocess.run(["bash", str(SETUP_PROMO_SH)], cwd=str(ROOT)).returncode
    if rc != 0:
        report.log_warn(
            "Promo Playwright: setup exited non-zero (optional) — run manually: "
            "./scripts/setup_promo_playwright.sh"
        )
        # Non-fatal: promo_render MCP is optional for core API/tests/CI.
        return 0
    report.log_ok("Promo Playwright: installed for MCP/backend Python")
    return 0


def run_runtime_extras(
    env_path: Path,
    *,
    dry_run: bool,
    report,
    enable_fs_policy_dev: bool = False,
    install_playwright: bool = True,
    skip_playwright: bool = False,
) -> int:
    """Full optional runtime extras chain."""
    rc = ensure_fs_policy_files(dry_run=dry_run, report=report)
    if rc != 0:
        return rc
    rc = ensure_fs_policy_wren_allowlist(env_path, dry_run=dry_run, report=report)
    if rc != 0:
        return rc
    rc = ensure_promo_env_keys(env_path, dry_run=dry_run, report=report)
    if rc != 0:
        return rc
    if enable_fs_policy_dev:
        rc = ensure_fs_policy_dev_active(env_path, dry_run=dry_run, report=report)
        if rc != 0:
            return rc
    if install_playwright:
        rc = setup_promo_playwright(dry_run=dry_run, report=report, skip=skip_playwright)
        if rc != 0:
            return rc
    return 0


def main() -> int:
    import argparse
    import sys

    class _Report:
        def log_ok(self, msg: str) -> None:
            print(f"[OK] {msg}")

        def log_warn(self, msg: str) -> None:
            print(f"[WARN] {msg}")

        def log_fail(self, msg: str) -> None:
            print(f"[FAIL] {msg}", file=sys.stderr)

    ap = argparse.ArgumentParser(
        description="FS policy templates + promo Playwright setup for AION runtime",
    )
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--enable-fs-policy-dev",
        action="store_true",
        help="Activate config/fs_policy.dev.yaml as config/fs_policy.yaml + AION_FS_POLICY_PATH",
    )
    ap.add_argument(
        "--skip-promo-playwright",
        action="store_true",
        help="Skip Playwright/Chromium install",
    )
    args = ap.parse_args()
    return run_runtime_extras(
        Path(args.env_file),
        dry_run=args.dry_run,
        report=_Report(),
        enable_fs_policy_dev=args.enable_fs_policy_dev,
        install_playwright=not args.skip_promo_playwright,
        skip_playwright=args.skip_promo_playwright,
    )


if __name__ == "__main__":
    raise SystemExit(main())
