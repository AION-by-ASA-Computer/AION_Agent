#!/usr/bin/env python3
"""
Show where an MCP server's environment variables come from, to debug values that
MCP Hub saved but the MCP process does not receive.

Three views of the same server:
1. registry  - the ``env`` written in config/mcp_registry(.local).yaml;
2. database  - the encrypted credentials in ``user_mcp_credentials`` (every owner);
3. spawn     - the env the backend would pass to the MCP process right now,
               resolved exactly as ``mcp_manager`` does at spawn time.

Secrets are never printed: each one is shown as its length plus a short SHA-256
fingerprint, so the three views can be compared (same fingerprint = same value).
``--show-secrets`` prints them in clear, for a local machine only.

Usage (from the repo root, or inside the backend container):
    python scripts/mcp_env_inspect.py as400_db2
    docker compose exec backend python scripts/mcp_env_inspect.py as400_db2
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _looks_secret(key: str) -> bool:
    """Same name heuristic as the admin API (key/token/secret/password/auth/pwd)."""
    return any(
        h in key.lower() for h in ("key", "token", "secret", "password", "auth", "pwd")
    )


def _describe(key: str, value: Any, show: bool) -> str:
    """Printable form of one value: placeholders as-is, secrets fingerprinted."""
    s = "" if value is None else str(value)
    if s.startswith("${") and s.endswith("}"):
        return f"{s}  (placeholder)"
    if not s:
        return "<empty>"
    if _looks_secret(key) and not show:
        digest = hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]
        return f"<secret, {len(s)} chars, sha256:{digest}>"
    return s


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("slug", help="MCP server slug as shown in MCP Hub")
    parser.add_argument(
        "--user",
        default="default",
        help="AION user id used to resolve the spawn env (default: 'default')",
    )
    parser.add_argument(
        "--show-secrets", action="store_true", help="print secrets in clear"
    )
    args = parser.parse_args()

    try:
        import src.aion_env  # noqa: F401  (loads .env like the backend does)
    except ImportError:
        pass

    from sqlalchemy import select

    from src.data.engine import get_async_session_maker, init_engine
    from src.data.models import UserMcpCredential
    from src.mcp_manager import mcp_manager
    from src.runtime.credential_store import decrypt_value, resolve_mcp_env_for_user

    init_engine()
    mcp_manager.load_registry()
    raw = (mcp_manager._registry.get(args.slug) or {}).get("env")
    if raw is None and args.slug not in mcp_manager._registry:
        known = ", ".join(
            sorted(k for k in mcp_manager._registry if not k.startswith("_"))
        )
        print(f"MCP '{args.slug}' not found in the registry. Known: {known}")
        return 1

    # 1) Registry: what MCP Hub wrote to the YAML.
    print(f"=== 1. Registry env of '{args.slug}' ===")
    for k, v in (raw or {}).items():
        print(f"  {k} = {_describe(k, v, args.show_secrets)}")

    # 2) Database: every encrypted credential stored for this slug, any owner.
    print("\n=== 2. Encrypted credentials in the DB ===")
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(UserMcpCredential)
                    .where(UserMcpCredential.server_slug == args.slug)
                    .order_by(
                        UserMcpCredential.credential_key, UserMcpCredential.user_id
                    )
                )
            )
            .scalars()
            .all()
        )
    if not rows:
        print("  (none)")
    for r in rows:
        try:
            plain = decrypt_value(r.value_encrypted)
        except Exception as exc:  # wrong AION_CREDENTIAL_ENCRYPTION_KEY, corrupted row
            plain = f"<cannot decrypt: {exc}>"
        print(
            f"  owner={r.user_id:<12} {r.credential_key} = "
            f"{_describe(r.credential_key, plain, args.show_secrets)}  "
            f"(updated {r.updated_at:%Y-%m-%d %H:%M})"
        )

    # 3) Spawn: the env the MCP process receives, resolved as mcp_manager does.
    print(f"\n=== 3. Env passed to the MCP process (user '{args.user}') ===")
    cfg: Dict[str, Any] = mcp_manager.get_server_config(args.slug) or {}
    resolved = await resolve_mcp_env_for_user(
        cfg.get("env") or {},
        user_id=args.user,
        tenant_id="default",
        server_slug=args.slug,
    )
    for k, v in resolved.items():
        print(f"  {k} = {_describe(k, v, args.show_secrets)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
