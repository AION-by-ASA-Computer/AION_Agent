"""Integration smoke test for long_run SSE path with mocked Pi worker."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_pi_worker_healthy_mock():
    from src.runtime.pi_runtime.pi_client import pi_worker_healthy

    with patch("src.runtime.pi_runtime.pi_client.httpx.AsyncClient") as mock_client:
        instance = mock_client.return_value.__aenter__.return_value
        instance.get = AsyncMock(
            return_value=type(
                "R", (), {"status_code": 200, "json": lambda self: {"ok": True}}
            )()
        )
        ok = await pi_worker_healthy(force=True)
        assert ok is True
