"""Unit tests for TurnContext builder (S2)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from haystack.dataclasses import ChatMessage

from src.runtime.turn.turn_context import TurnContext, build_turn_context


@pytest.mark.anyio
async def test_build_turn_context_minimal(monkeypatch):
    """build_turn_context assembles messages and returns a TurnContext dataclass."""
    from src.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("AION_CONTEXT_COMPRESS_ENABLED", "0")
    monkeypatch.setenv("AION_STM_MAX_TURNS", "5")
    get_settings.cache_clear()

    emitted: List[Dict[str, Any]] = []
    stm_msgs = [ChatMessage.from_user("prior turn")]

    pipeline = MagicMock()
    pipeline.session_id = "sess-turn-ctx"
    pipeline.profile_name = "aion_std"
    pipeline.user_id = "user-1"
    pipeline.agent = object()
    pipeline._format_attachments_block = MagicMock(return_value="")
    pipeline._augment_user_input = AsyncMock(return_value="augmented hello")
    pipeline._apply_context_compression = AsyncMock(
        side_effect=lambda msgs, force=False, **kwargs: (list(msgs), False, False)
    )

    _ltm = SimpleNamespace(
        wake_up=AsyncMock(return_value=SimpleNamespace(blocks=[])),
        build_augmented_user_text=lambda u, _m, _w: u,
    )
    monkeypatch.setattr("src.memory.ltm_orchestrator.ltm_orchestrator", _ltm)
    monkeypatch.setattr(
        "src.api.history.history_manager.get_window",
        AsyncMock(return_value=list(stm_msgs)),
    )
    monkeypatch.setattr(
        "src.runtime.redis_client.redis_consume_force_compact",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "src.runtime.hooks.hook_registry.dispatch",
        AsyncMock(return_value=SimpleNamespace(modified_payload={})),
    )
    monkeypatch.setattr(
        "src.agent_profile.profile_manager.get_profile",
        lambda _name: None,
    )
    monkeypatch.setattr(
        "src.memory.context_compressor.estimate_agent_overhead_tokens",
        lambda _agent: 100,
    )
    monkeypatch.setattr(
        "src.memory.context_compressor.estimate_full_prompt_tokens",
        lambda _agent, _msgs: {
            "total": 500,
            "max_prompt": 8000,
            "overhead": 100,
        },
    )
    monkeypatch.setattr(
        "src.memory.context_compressor.get_default_compressor",
        lambda: SimpleNamespace(
            max_message_tokens=lambda _oh: 4000,
            should_compress=lambda *_a, **_k: False,
            total_with_overhead=lambda *_a, **_k: 500,
            compress_trigger_tokens=lambda: 6000,
            keep_last=4,
        ),
    )

    ctx = await build_turn_context(
        pipeline,
        user_input="hello",
        attachments=None,
        turn_attachments=None,
        message_source="user_input",
        effective_agent_mode="chat",
        sql_query_project=None,
        plan_execution_task_id=None,
        user_message_id="u-1",
        assistant_message_id="a-1",
        track_sse_callback=emitted.append,
    )

    assert isinstance(ctx, TurnContext)
    assert ctx.augmented_user == "augmented hello"
    assert ctx.effective_agent_mode == "chat"
    assert ctx.qm_project == "default"
    assert len(ctx.messages) >= 2
    assert ctx.context_stats["message_count"] == len(ctx.messages)
    assert not emitted
    get_settings.cache_clear()


def test_turn_context_dataclass_fields():
    ctx = TurnContext(
        messages=[],
        context_stats={"total": 0, "message_count": 0},
        augmented_user="x",
        prompt_inject_layers=[],
        qm_project="default",
        qm_profile_slug="aion_std",
        effective_agent_mode="chat",
    )
    assert ctx.qm_profile_slug == "aion_std"


def test_format_attachments_block_separation():
    from src.agent_pipeline import AgentPipeline

    pipeline = AgentPipeline(
        agent=None,
        session_id="sess-1",
        profile_name="aion_std",
    )

    attachments = [
        {
            "relative_path": "uploads/1_file1.txt",
            "original_name": "file1.txt",
            "mime": "text/plain",
        },
        {
            "relative_path": "uploads/2_file2.txt",
            "original_name": "file2.txt",
            "mime": "text/plain",
        },
    ]
    turn_attachments = [
        {
            "relative_path": "uploads/2_file2.txt",
            "original_name": "file2.txt",
            "mime": "text/plain",
        }
    ]

    block = pipeline._format_attachments_block(attachments, turn_attachments)

    assert "Newly uploaded files in this prompt:" in block
    assert "uploads/2_file2.txt" in block
    assert "Historical files available from previous turns:" in block
    assert "uploads/1_file1.txt" in block
    assert "IMPORTANT: A new document has been uploaded in this prompt." in block
    assert "NOTE: The historical files listed above are available" in block


@pytest.mark.anyio
async def test_build_turn_context_clears_loaded_skills_on_fresh_start(
    tmp_path, monkeypatch
):
    from src.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("AION_CONTEXT_COMPRESS_ENABLED", "0")

    # Mock session_root to return our tmp_path
    monkeypatch.setattr("src.session_workspace.session_root", lambda sid: tmp_path)

    # Create stale skill asset markers
    assets_dir = tmp_path / ".aion_skill_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "plane.json").write_text("{}", encoding="utf-8")

    pipeline = MagicMock()
    pipeline.session_id = "test-sess-cleanup"
    pipeline.profile_name = "aion_std"
    pipeline.user_id = "user-1"
    pipeline.agent = object()
    pipeline._format_attachments_block = MagicMock(return_value="")
    pipeline._augment_user_input = AsyncMock(return_value="augmented")
    pipeline._apply_context_compression = AsyncMock(
        side_effect=lambda msgs, **kwargs: (list(msgs), False, False)
    )

    # Mock history_manager.get_window to return an EMPTY list (fresh start)
    monkeypatch.setattr(
        "src.api.history.history_manager.get_window", AsyncMock(return_value=[])
    )

    _ltm = SimpleNamespace(
        wake_up=AsyncMock(return_value=SimpleNamespace(blocks=[])),
        build_augmented_user_text=lambda u, _m, _w: u,
    )
    monkeypatch.setattr("src.memory.ltm_orchestrator.ltm_orchestrator", _ltm)
    monkeypatch.setattr(
        "src.runtime.redis_client.redis_consume_force_compact",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "src.runtime.hooks.hook_registry.dispatch",
        AsyncMock(return_value=SimpleNamespace(modified_payload={})),
    )
    monkeypatch.setattr(
        "src.agent_profile.profile_manager.get_profile", lambda _name: None
    )
    monkeypatch.setattr(
        "src.memory.context_compressor.estimate_agent_overhead_tokens",
        lambda _agent: 100,
    )
    monkeypatch.setattr(
        "src.memory.context_compressor.estimate_full_prompt_tokens",
        lambda _agent, _msgs: {"total": 500, "max_prompt": 8000, "overhead": 100},
    )
    monkeypatch.setattr(
        "src.memory.context_compressor.get_default_compressor",
        lambda: SimpleNamespace(
            max_message_tokens=lambda _oh: 4000,
            should_compress=lambda *_a, **_k: False,
            total_with_overhead=lambda *_a, **_k: 500,
            compress_trigger_tokens=lambda: 6000,
            keep_last=4,
        ),
    )

    # Assert that assets_dir exists before building the context
    assert assets_dir.is_dir()
    assert (assets_dir / "plane.json").is_file()

    # Build turn context on fresh session start
    await build_turn_context(
        pipeline,
        user_input="hello",
        attachments=None,
        turn_attachments=None,
        message_source="user_input",
        effective_agent_mode="chat",
        sql_query_project=None,
        plan_execution_task_id=None,
        user_message_id="u-1",
        assistant_message_id="a-1",
    )

    # Assert that assets_dir has been successfully cleared
    assert not assets_dir.exists()
