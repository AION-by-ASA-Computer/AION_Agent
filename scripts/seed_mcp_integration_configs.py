#!/usr/bin/env python3
"""
Popola la tabella mcp_server_configs con gli slug presenti nel registry MCP merge.
Idempotente: salta slug già presenti. Eseguire dopo le migration Alembic.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main() -> None:
    try:
        import src.aion_env  # noqa: F401
    except ImportError:
        pass

    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import init_engine
    from src.mcp_integration_sync import sync_all_mcp_server_configs_from_registry
    from src.mcp_manager import mcp_manager

    eng = init_engine()
    await ensure_bootstrap_schema(eng)
    mcp_manager.load_registry()

    summary = await sync_all_mcp_server_configs_from_registry()
    print(
        f"Done. created={summary['created']} updated={summary['updated']} "
        f"skipped={summary['skipped']} total={summary['total']}"
    )
    print("Per schema/env senza toccare registry: scripts/sync_mcp_integration_from_catalog.py")


if __name__ == "__main__":
    asyncio.run(main())
