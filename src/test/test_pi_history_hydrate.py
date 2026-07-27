from types import SimpleNamespace

from src.runtime.pi_runtime.pi_turn_runner import (
    _count_pi_dialogue_messages,
    format_pi_history_prefix,
)


def test_format_pi_history_prefix_skips_current_turn():
    msgs = [
        SimpleNamespace(role="user", content="crea excel mondiale 2026"),
        SimpleNamespace(role="assistant", content="raccolgo dati da Wikipedia"),
        SimpleNamespace(role="user", content="Riprova"),
    ]
    out = format_pi_history_prefix(msgs, max_chars=5000)
    assert "Previous messages in this chat" in out
    assert "mondiale 2026" in out
    assert "Wikipedia" in out
    assert "Riprova" not in out


def test_format_pi_history_prefix_empty_for_first_turn():
    msgs = [SimpleNamespace(role="user", content="ciao")]
    assert format_pi_history_prefix(msgs) == ""


def test_count_pi_dialogue_messages():
    rows = [
        {"role": "system", "content": "x"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ]
    assert _count_pi_dialogue_messages(rows) == 2
