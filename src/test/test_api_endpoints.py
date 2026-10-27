import asyncio
from pathlib import Path
from fastapi.testclient import TestClient


async def _reset_unified_db(monkeypatch, tmp_path: Path) -> None:
    import src.data.engine as engine

    if engine._engine is not None:
        await engine._engine.dispose()
    engine._engine = None
    engine._session_factory = None

    # Configure test environment variables before import/startup of main app
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "default")
    monkeypatch.setenv(
        "AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'test_aion.db'}"
    )
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "0")
    monkeypatch.setenv("AION_ADMIN_PASSWORD_AUTH", "0")
    monkeypatch.setenv("AION_REDIS_FALLBACK_LOCAL", "1")
    monkeypatch.delenv("AION_REDIS_URL", raising=False)


def test_api_endpoints_workflow(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)

        # Ensure config and mcp_servers default profiles exist for test loading
        # (This avoids failures if profiles directory hasn't been created yet)
        profiles_dir = tmp_path / "config" / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)

        # Create a dummy profile
        dummy_profile_content = """
name: Generic Assistant
description: Standard test profile
instructions: You are a helpful assistant.
skills:
  - core_protocol
mcp_servers: []
"""
        with open(profiles_dir / "generic_assistant.yaml", "w", encoding="utf-8") as f:
            f.write(dummy_profile_content)

        # Point the profile manager to the dummy config folder
        monkeypatch.setattr("src.agent_profile.profile_manager.base_path", profiles_dir)
        # Reload profiles
        from src.agent_profile import profile_manager

        profile_manager.load_all()

        # Import FastAPI app
        from src.api.main import app

        # Use context manager to start/stop FastAPI lifespan (runs migrations/bootstrap)
        with TestClient(app) as client:
            # 1. Test /health endpoint
            res_health = client.get("/health")
            assert res_health.status_code == 200
            data_health = res_health.json()
            assert data_health["status"] == "ok"
            assert data_health["service"] == "aion-api"

            # 2. Test /auth/status endpoint
            res_auth = client.get("/auth/status")
            assert res_auth.status_code == 200
            data_auth = res_auth.json()
            assert data_auth["password_auth_enabled"] is False
            assert data_auth["admin_password_auth_enabled"] is False

            # 3. Test /profiles endpoint (compat route)
            res_profiles = client.get("/profiles")
            assert res_profiles.status_code == 200
            data_profiles = res_profiles.json()
            assert isinstance(data_profiles, list)
            assert len(data_profiles) > 0
            assert any(p["slug"] == "generic_assistant" for p in data_profiles)

            # 4. Test /debug/prompt/{profile_name} endpoint
            res_prompt = client.get("/debug/prompt/generic_assistant")
            assert res_prompt.status_code == 200
            data_prompt = res_prompt.json()
            assert "prompt" in data_prompt
            assert "Role: Generic Assistant" in data_prompt["prompt"]

            # 5. Test /sessions/{session_id}/charts endpoint
            res_charts = client.get("/sessions/test-session-123/charts")
            assert res_charts.status_code == 200
            data_charts = res_charts.json()
            assert "charts" in data_charts
            assert isinstance(data_charts["charts"], list)
            # Route del contratto API: esclusa dal Sunset di /sessions/*.
            assert "Deprecation" not in res_charts.headers
            assert "Sunset" not in res_charts.headers
            res_files = client.get("/sessions/test-session-123/files")
            assert res_files.headers.get("Deprecation") == "true"
            assert "Sunset" in res_files.headers

            # 6. Test /chat/stop endpoint
            res_stop = client.post("/chat/stop?session_id=test-session-123")
            assert res_stop.status_code == 200
            data_stop = res_stop.json()
            assert data_stop["ok"] is True
            assert data_stop["session_id"] == "test-session-123"

    asyncio.run(run())


def test_feedback_endpoints(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)

        # Set up a dummy profile
        profiles_dir = tmp_path / "config" / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        dummy_profile_content = """
name: Generic Assistant
description: Standard test profile
instructions: You are a helpful assistant.
skills:
  - core_protocol
mcp_servers: []
"""
        with open(profiles_dir / "generic_assistant.yaml", "w", encoding="utf-8") as f:
            f.write(dummy_profile_content)

        monkeypatch.setattr("src.agent_profile.profile_manager.base_path", profiles_dir)
        from src.agent_profile import profile_manager

        profile_manager.load_all()

        from src.api.main import app
        from src.data.history_bridge import UnifiedHistoryBridge
        from src.data.engine import get_async_session_maker

        # Seed conversation and message
        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-test-feedback",
            "user",
            "What is the capital of Italy?",
            user_id="user-1",
            message_id="msg-user-1",
        )
        await bridge.add_message(
            "conv-test-feedback",
            "assistant",
            "The capital of Italy is Rome.",
            user_id="user-1",
            message_id="msg-assistant-1",
        )

        # Explicitly set rating/comment on msg-assistant-1 in the DB
        async with get_async_session_maker()() as session:
            from src.data.history_bridge import fetch_message_by_id

            msg = await fetch_message_by_id(session, "msg-assistant-1")
            assert msg is not None
            msg.rating = -1
            msg.feedback_comment = "Incorrect tone"
            msg.profile_name = "generic_assistant"
            await session.commit()

        with TestClient(app) as client:
            # Aggregated counts only: no content, comments, prompts or ids (privacy)
            res_get = client.get("/admin/feedback?days=7")
            assert res_get.status_code == 200
            data = res_get.json()
            assert data["window_days"] == 7
            assert data["totals"] == {"positive": 0, "negative": 1}
            assert data["by_profile"] == [
                # Stored slug is resolved to the profile's display name
                {
                    "profile": "Generic Assistant",
                    "slug": "generic_assistant",
                    "positive": 0,
                    "negative": 1,
                }
            ]
            assert [r["negative"] for r in data["by_model"]] == [1]
            raw = res_get.text
            for leaked in (
                "Rome",
                "capital of Italy",
                "Incorrect tone",
                "user-1",
                "conv-test-feedback",
                "msg-assistant-1",
            ):
                assert leaked not in raw

            # Per-message feedback management and conversation reading are gone
            assert client.delete("/admin/feedback/msg-assistant-1").status_code in (
                404,
                405,
            )
            for path in (
                "/admin/conversations/global",
                "/admin/conversations/conv-test-feedback/messages",
                "/admin/conversations/conv-test-feedback/render-audit",
            ):
                assert client.get(path).status_code == 404, path

    asyncio.run(run())
