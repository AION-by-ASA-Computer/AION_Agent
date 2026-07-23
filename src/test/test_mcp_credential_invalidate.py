import asyncio
from unittest.mock import AsyncMock, patch

from src.runtime.mcp_credential_invalidate import invalidate_mcp_credentials_runtime


def test_invalidate_mcp_credentials_runtime_restarts_user_workers() -> None:
    async def run() -> None:
        with patch(
            "src.mcp_manager.mcp_manager.restart_workers_for_user",
            new_callable=AsyncMock,
            return_value=2,
        ) as restart:
            stopped = await invalidate_mcp_credentials_runtime(
                "alice",
                "any-mcp-slug",
                tenant_id="default",
            )
            assert stopped == 2
            restart.assert_awaited_once_with(
                "alice",
                server_slug="any-mcp-slug",
                tenant_id="default",
            )

    asyncio.run(run())
