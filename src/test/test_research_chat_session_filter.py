"""Research jobs scoped to chat session."""

from src.research.handler import ResearchHandler


def test_matches_chat_session():
    assert ResearchHandler._matches_chat_session({"chat_session_id": "abc"}, "abc")
    assert not ResearchHandler._matches_chat_session({"chat_session_id": "abc"}, "xyz")
    assert not ResearchHandler._matches_chat_session({}, "abc")
    assert ResearchHandler._matches_chat_session({"chat_session_id": "abc"}, None)
