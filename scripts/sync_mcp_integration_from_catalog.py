#!/usr/bin/env python3
"""
Sincronizza mcp_server_configs dal registry MCP + catalogo connettori.
Non modifica env nel registry salvo --apply-registry-env.

Uso:
  ./.venv/bin/python scripts/sync_mcp_integration_from_catalog.py
  ./.venv/bin/python scripts/sync_mcp_integration_from_catalog.py --slug clickup
  ./.venv/bin/python scripts/sync_mcp_integration_from_catalog.py --apply-registry-env --slug clickup
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main() -> int:
    try:
        import src.aion_env  # noqa: F401
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Sync MCP integration policy from catalog")
    parser.add_argument("--slug", help="Sync only this registry server slug")
    parser.add_argument(
        "--apply-registry-env",
        action="store_true",
        help="Apply suggested env placeholders to mcp_registry.local.yaml (per inferred mode)",
    )
    args = parser.parse_args()

    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import init_engine
    from src.mcp_integration_sync import (
        build_integration_preview,
        infer_credential_mode,
        merge_suggested_env_into_registry,
        sync_all_mcp_server_configs_from_registry,
        sync_mcp_server_config_from_registry,
    )
    from src.mcp_manager import mcp_manager

    eng = init_engine()
    await ensure_bootstrap_schema(eng)
    mcp_manager.load_registry()

    if args.slug:
        row = await sync_mcp_server_config_from_registry(args.slug)
        if not row:
            print(f"ERROR: slug '{args.slug}' not in registry")
            return 1
        preview = build_integration_preview(args.slug)
        mode = preview.get("credential_mode") or "none"
        print(f"  synced: {args.slug} mode={mode} schema_fields={len(preview.get('credential_schema') or [])}")
        if preview.get("warnings"):
            for w in preview["warnings"]:
                print(f"  WARN: {w}")
        if args.apply_registry_env and mode in ("per_user", "org_shared"):
            r = merge_suggested_env_into_registry(args.slug, mode, preserve_existing_keys=True)
            print(f"  registry env updated: {list((r.get('env') or {}).keys())}")
        return 0

    summary = await sync_all_mcp_server_configs_from_registry()
    print(
        f"Sync complete: created={summary['created']} updated={summary['updated']} "
        f"skipped={summary['skipped']} total={summary['total']}"
    )

    no_connector: list[str] = []
    global_secret_candidates: list[str] = []
    aligned: list[str] = []

    for slug in mcp_manager.get_all_servers():
        if not slug or str(slug).startswith("_"):
            continue
        preview = build_integration_preview(slug)
        if not preview.get("ok"):
            continue
        conn = preview.get("aion_connector_id")
        mode = preview.get("credential_mode") or "none"
        if not conn and not preview.get("credential_schema"):
            no_connector.append(slug)
        elif mode == "org_shared" and preview.get("warnings"):
            global_secret_candidates.append(f"{slug} ({mode})")
        else:
            aligned.append(f"{slug} ({mode}, {len(preview.get('credential_schema') or [])} fields)")

    if no_connector:
        print("\nSenza match catalogo / schema vuoto:")
        for s in no_connector:
            print(f"  - {s}")
    if global_secret_candidates:
        print("\nCandidati revisione (org_shared o warning env):")
        for s in global_secret_candidates:
            print(f"  - {s}")
    print(f"\nAllineati: {len(aligned)}")
    for line in aligned[:20]:
        print(f"  - {line}")
    if len(aligned) > 20:
        print(f"  ... +{len(aligned) - 20} altri")

    if args.apply_registry_env:
        applied = 0
        for slug in mcp_manager.get_all_servers():
            if not slug or str(slug).startswith("_"):
                continue
            cfg = mcp_manager.get_server_config(slug) or {}
            catalog_mode = infer_credential_mode(
                cfg,
                (build_integration_preview(slug).get("connector")),
            )
            if catalog_mode in ("per_user", "org_shared"):
                merge_suggested_env_into_registry(slug, catalog_mode, preserve_existing_keys=True)
                applied += 1
        print(f"\nRegistry env patch (preserve existing): {applied} server")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
