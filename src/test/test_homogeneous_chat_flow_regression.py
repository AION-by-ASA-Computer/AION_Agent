from src.chat_message_visibility import is_replay_visible_message
from src.data.message_roles import normalize_message_role


def test_internal_trigger_not_persisted_as_user():
    assert normalize_message_role("internal") == "internal"
    assert normalize_message_role("system") == "system"
    assert normalize_message_role("user") == "user"


def test_plan_raw_not_shown_when_artifact_exists():
    raw_plan = "<plan>\n# Plan\n## Goal\nx\n## Tasks\n- [ ] `t1` **Task** (profile: p) (deps: none)\n</plan>"
    assert is_replay_visible_message("assistant", raw_plan) is False


def test_resume_filters_empty_technical_messages():
    assert is_replay_visible_message("assistant", "") is False
    assert is_replay_visible_message("tool", "   ") is False
    assert is_replay_visible_message("assistant", "testo reale") is True

