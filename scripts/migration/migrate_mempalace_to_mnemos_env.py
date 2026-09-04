#!/usr/bin/env python3
"""
Migrate legacy MemPalace navigation env → Mnemos LTM (conditional).

Runs only when MemPalace is still detected (env keys or data/mempalace/).
Skips when AION_MEMORY_STACK=mnemos is already set.

Usage:
  python scripts/migrate_mempalace_to_mnemos_env.py
  python scripts/migrate_mempalace_to_mnemos_env.py --env .env --dry-run
  python scripts/migrate_mempalace_to_mnemos_env.py -y
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.env_tuning_profiles import (  # noqa: E402
    BENCHMARK_ONLY_ENV_KEYS,
    MNEMOS_OPTIMAL,
    MEMPALACE_ENV_KEYS,
    ROOT as ENV_ROOT,
    apply_env_profile,
    backup_env_file,
    detect_mempalace_legacy,
    merge_missing_only,
    mnemos_migration_complete,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove MemPalace env keys and apply optimal Mnemos profile."
    )
    parser.add_argument(
        "--env",
        default=str(ROOT / ".env"),
        help="Path to .env (default: repo root .env)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    parser.add_argument(
        "--prune-benchmark-keys",
        action="store_true",
        help="Also remove AION_LME_V2_* keys (benchmark-only clutter in prod)",
    )
    parser.add_argument(
        "--apply-runtime-tuning",
        action="store_true",
        help="Also apply OPTIMAL_RUNTIME_TUNING (harness v2, TOON, compression)",
    )
    args = parser.parse_args()

    env_path = Path(args.env).resolve()
    if not env_path.is_file():
        print(f"[error] .env not found: {env_path}", file=sys.stderr)
        return 2

    if mnemos_migration_complete(env_path):
        print("[skip] Mnemos migration already complete (AION_MEMORY_STACK=mnemos).")
        return 0

    if not detect_mempalace_legacy(env_path, ENV_ROOT):
        print("[skip] MemPalace not detected — nothing to migrate.")
        return 0

    remove_keys = set(MEMPALACE_ENV_KEYS)
    if args.prune_benchmark_keys:
        remove_keys |= BENCHMARK_ONLY_ENV_KEYS

    set_values = dict(MNEMOS_OPTIMAL)
    if args.apply_runtime_tuning:
        from scripts.env_tuning_profiles import OPTIMAL_RUNTIME_TUNING

        set_values.update(OPTIMAL_RUNTIME_TUNING)

    missing = merge_missing_only(env_path, set_values)
    print(
        f"MemPalace -> Mnemos: will set/update {len(set_values)} keys, "
        f"remove {len(remove_keys)} keys."
    )
    if missing:
        print(f"  New keys: {len(missing)}")

    if not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            print(
                "[error] Non-interactive shell: pass -y to confirm migration.",
                file=sys.stderr,
            )
            return 1
        ans = input("Proceed with MemPalace -> Mnemos migration? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 1

    if not args.dry_run:
        backup = backup_env_file(env_path)
        print(f"[backup] {backup}")

    result = apply_env_profile(
        env_path,
        set_values=set_values,
        remove_keys=sorted(remove_keys),
        dry_run=args.dry_run,
        skip_protected=True,
    )

    mode = "would apply" if args.dry_run else "applied"
    print(f"[ok] Migration {mode}:")
    print(f"  set: {len(result['applied'])} keys")
    print(f"  removed: {len(result['removed'])} keys")
    if result["removed"]:
        for key in sorted(result["removed"])[:12]:
            print(f"    - {key}")
        if len(result["removed"]) > 12:
            print(f"    ... and {len(result['removed']) - 12} more")
    if not args.dry_run:
        print(
            "\nRestart the backend after migration. "
            "Optional: python scripts/apply_optimal_aion_env.py for full runtime tuning."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
