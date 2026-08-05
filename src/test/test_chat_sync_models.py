"""Unit tests for POST /v1/chat sync request models."""

from src.api.v1.chat import ChatSyncBody


def test_chat_sync_body_defaults_for_automation():
    body = ChatSyncBody(message="hello")
    assert body.message == "hello"
    assert body.profile == "aion_std"
    assert body.conversation_id is None
    assert body.message_source == "internal_trigger"
    assert body.timeout_seconds == 300.0


def test_chat_sync_body_aliases():
    body = ChatSyncBody(
        message="hi",
        profile_slug="ops",
        session_id="sess-1",
        timeout_seconds=60,
    )
    assert body.profile == "ops"
    assert body.conversation_id == "sess-1"
    assert body.timeout_seconds == 60.0
