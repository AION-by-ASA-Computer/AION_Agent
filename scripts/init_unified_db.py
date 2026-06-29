#!/usr/bin/env python3
"""
Standalone script to initialize the unified AION database (aion.db).
Creates tables, triggers, and FTS5 virtual tables if they don't exist.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

async def main():
    print("=== AION Unified Database Initializer ===")
    
    # Pre-load env if exists
    try:
        import src.aion_env
    except ImportError:
        pass
        
    from src.data.engine import init_engine
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.migrations import run_migrations
    
    db_url = os.getenv("AION_DB_URL", "sqlite+aiosqlite:///data/aion.db")
    print(f"Target DB: {db_url}")
    
    try:
        eng = init_engine()
        print("[1/4] Engine initialized.")
        
        print("[2/4] Bootstrapping schema (Tables, FTS5, Triggers, Default Tenant)...")
        await ensure_bootstrap_schema(eng)
        print("      Bootstrap completed.")
        
        print("[3/4] Running incremental migrations (Alembic)...")
        run_migrations()
        print("      Migrations completed.")

        from src.data.bootstrap import patch_sqlite_schema_drift

        print("[3b/4] Applying SQLite schema drift patches (legacy DBs)...")
        await patch_sqlite_schema_drift(eng)
        print("      Schema patches completed.")

        from src.runtime.timeline_backfill import backfill_message_timelines

        print("[4/4] Backfilling message timelines (idempotent)...")
        n = await backfill_message_timelines()
        if n:
            print(f"      Backfilled timeline_json on {n} assistant message(s).")
        else:
            print("      No assistant messages needed timeline backfill.")
        
        print("\nSUCCESS: Database is ready for AION Agent.")
        
    except Exception as e:
        print(f"\nFATAL ERROR during initialization: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
