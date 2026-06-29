"""Research API owner resolution (open chat + X-AION-User-Id)."""

from src.api.auth_login import ChatAuthIdentity
from src.api.research import resolve_research_owner


def test_research_owner_open_chat_uses_header():
    auth = ChatAuthIdentity(via="anonymous", identifier=None)
    assert resolve_research_owner(auth, "demo") == "demo"


def test_research_owner_jwt_overrides_header():
    auth = ChatAuthIdentity(via="chat_token", identifier="alice", user_row_id="1")
    assert resolve_research_owner(auth, "demo") == "alice"
