"""UI language resolution and prompt injection."""

import os

import pytest

from src.memory.context_compressor import compaction_summary_prompt
from src.runtime.user_language import (
    build_ui_language_prompt_section,
    default_ui_language,
    normalize_ui_language,
    resolve_compaction_language,
)


def test_normalize_ui_language():
    assert normalize_ui_language("en-US") == "en"
    assert normalize_ui_language("it") == "it"
    assert normalize_ui_language("ja") is None
    assert normalize_ui_language(None) is None


def test_build_ui_language_prompt_section_explicit():
    section = build_ui_language_prompt_section("en")
    assert "Always reply in English" in section
    assert "Response language" in section


def test_default_ui_language_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AION_DEFAULT_UI_LANGUAGE", raising=False)
    assert default_ui_language() == "en"
    monkeypatch.setenv("AION_DEFAULT_UI_LANGUAGE", "fr")
    assert default_ui_language() == "fr"


def test_compaction_prompt_uses_default_not_italian(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AION_DEFAULT_UI_LANGUAGE", raising=False)
    prompt = compaction_summary_prompt(None)
    assert "Respond in English" in prompt
    assert "italiano" not in prompt.lower()


def test_resolve_compaction_language_prefers_db():
    assert resolve_compaction_language("alice", "de") == "de"
    assert resolve_compaction_language("default", None) == default_ui_language()
