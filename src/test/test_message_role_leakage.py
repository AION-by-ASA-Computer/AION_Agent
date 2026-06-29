from src.api.history import ChatHistoryManager
from src.chat_message_visibility import normalize_step_visual
from src.data.history_bridge import UnifiedHistoryBridge
from src.data.message_roles import is_ui_visible_role, normalize_message_role


def test_normalize_role_unknown_to_internal():
    assert normalize_message_role("skill") == "skill"
    assert normalize_message_role("developer") == "developer"
    assert normalize_message_role("weird_role") == "internal"
    assert normalize_message_role("") == "internal"


def test_ui_visible_only_user_assistant():
    assert is_ui_visible_role("user") is True
    assert is_ui_visible_role("assistant") is True
    assert is_ui_visible_role("system") is False
    assert is_ui_visible_role("tool") is False
    assert is_ui_visible_role("internal") is False


def test_history_row_to_chat_message_does_not_map_internal_to_user():
    hm = ChatHistoryManager()
    assert hm._row_to_chat_message("system", "x", None) is None
    assert hm._row_to_chat_message("tool", "x", "t1") is None
    assert hm._row_to_chat_message("unknown", "x", None) is None


def test_unified_bridge_row_to_chat_message_does_not_map_internal_to_user():
    bridge = UnifiedHistoryBridge()
    assert bridge._row_to_chat_message("system", "x", None) is None
    assert bridge._row_to_chat_message("tool", "x", "t1") is None
    assert bridge._row_to_chat_message("unknown", "x", None) is None


def test_step_visual_normalization():
    sd = {"type": "tool", "name": "whatever"}
    normalize_step_visual(sd, "user", "giuseppe")
    assert sd["type"] == "user_message"
    assert sd["name"] == "giuseppe"
    normalize_step_visual(sd, "assistant", "giuseppe")
    assert sd["type"] == "assistant_message"
    assert sd["name"] == "AION Agent"

