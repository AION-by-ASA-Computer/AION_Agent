#!/usr/bin/env python3
"""
Apply optimal AION runtime tuning to an existing .env (optional, idempotent-ish).

Touches harness v2, TOON tool format, context compression, tool offload, web tools.
Never overwrites sandbox/podman/URL/secrets (see env_tuning_profiles.PROTECTED_*).

Usage:
  python scripts/apply_optimal_aion_env.py --dry-run
  python scripts/apply_optimal_aion_env.py --force -y
  python scripts/apply_optimal_aion_env.py --only harness,compression,offload
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.env_tuning_profiles import (  # noqa: E402
    BENCHMARK_ONLY_ENV_KEYS,
    OPTIMAL_RUNTIME_TUNING,
    apply_env_profile,
    backup_env_file,
    env_key_map,
    is_protected_env_key,
    merge_missing_only,
)

TUNING_GROUPS: dict[str, frozenset[str]] = {
    "harness": frozenset(k for k in OPTIMAL_RUNTIME_TUNING if k.startswith("AION_HARNESS_V2_")),
    "toon": frozenset(
        {
            "AION_TOOL_RESULT_FORMAT",
            "AION_TOOL_WEB_FETCH_MAX_CHARS",
            "AION_TOOL_WEB_SEARCH_MAX_CHARS",
            "AION_TOON_WEB_SEARCH_SNIPPET_CHARS",
        }
    ),
    "offload": frozenset(
        k
        for k in OPTIMAL_RUNTIME_TUNING
        if k.startswith("AION_TOOL_OFFLOAD_") or k.startswith("AION_TOOL_LEDGER_")
    ),
    "compression": frozenset(
        k for k in OPTIMAL_RUNTIME_TUNING if k.startswith("AION_CONTEXT_COMPRESS_")
        or k in {"AION_MODEL_MAX_CONTEXT"}
    ),
    "web": frozenset(
        k
        for k in OPTIMAL_RUNTIME_TUNING
        if k.startswith("AION_WEB_") or k.startswith("AION_WIKIPEDIA_")
    ),
    "tools": frozenset(
        {
            "AION_TOOL_CIRCUIT_BREAKER_ENABLED",
            "AION_TOOL_RESULT_MAX_CHARS",
            "AION_CHROMA_SHARED_EMBEDDING_CACHE",
        }
    ),
}


def _select_keys(groups: str | None) -> dict[str, str]:
    if not groups:
        return dict(OPTIMAL_RUNTIME_TUNING)
    names = [g.strip().lower() for g in groups.split(",") if g.strip()]
    unknown = [n for n in names if n not in TUNING_GROUPS]
    if unknown:
        valid = ", ".join(sorted(TUNING_GROUPS))
        raise SystemExit(f"Unknown group(s): {', '.join(unknown)}. Valid: {valid}")
    keys: set[str] = set()
    for name in names:
        keys |= set(TUNING_GROUPS[name])
    return {k: v for k, v in OPTIMAL_RUNTIME_TUNING.items() if k in keys}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply optimal AION runtime tuning keys to .env"
    )
    parser.add_argument("--env", default=str(ROOT / ".env"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing values (still skips protected keys)",
    )
    parser.add_argument(
        "--only",
        metavar="GROUPS",
        help="Comma-separated: harness,toon,offload,compression,web,tools",
    )
    parser.add_argument(
        "--prune-benchmark-keys",
        action="store_true",
        help="Remove AION_LME_V2_* benchmark keys from .env",
    )
    parser.add_argument("-y", "--yes", action="store_true")
    args = parser.parse_args()

    env_path = Path(args.env).resolve()
    if not env_path.is_file():
        print(f"[error] .env not found: {env_path}", file=sys.stderr)
        return 2

    try:
        profile = _select_keys(args.only)
    except SystemExit as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    before = env_key_map(env_path)
    if args.force:
        to_set = {
            k: v
            for k, v in profile.items()
            if not is_protected_env_key(k)
        }
    else:
        to_set = merge_missing_only(env_path, profile)

    remove_keys: list[str] = []
    if args.prune_benchmark_keys:
        remove_keys = sorted(k for k in BENCHMARK_ONLY_ENV_KEYS if k in before)

    if not to_set and not remove_keys:
        print("[ok] All selected tuning keys already present; nothing to do.")
        return 0

    print(f"Tuning: {len(to_set)} key(s) to set, {len(remove_keys)} to remove.")
    if to_set and not args.force:
        print("  (missing keys only — use --force to overwrite existing values)")

    changes_preview = []
    for k, v in sorted(to_set.items()):
        old = before.get(k)
        if old is not None and old != v:
            changes_preview.append(f"  {k}: {old!r} → {v!r}")
        elif old is None:
            changes_preview.append(f"  {k}: (new) = {v!r}")
    for line in changes_preview[:20]:
        print(line)
    if len(changes_preview) > 20:
        print(f"  ... and {len(changes_preview) - 20} more")

    if not args.dry_run and not args.yes and (to_set or remove_keys):
        if not sys.stdin.isatty():
            print("[error] Non-interactive: pass -y to confirm.", file=sys.stderr)
            return 1
        ans = input("Apply optimal tuning? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 1

    if not args.dry_run:
        backup = backup_env_file(env_path)
        print(f"[backup] {backup}")

    result = apply_env_profile(
        env_path,
        set_values=to_set,
        remove_keys=remove_keys,
        dry_run=args.dry_run,
        skip_protected=True,
    )

    mode = "would apply" if args.dry_run else "applied"
    print(f"[ok] Tuning {mode}: set {len(result['applied'])}, removed {len(result['removed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
