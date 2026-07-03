"""Tests for model-specific tool gating."""

from types import SimpleNamespace

from src.runtime.model_tool_policy import filter_tools_for_model, model_prefers_apply_patch


def _tool(name: str):
    return SimpleNamespace(name=name)


def test_gpt_prefers_apply_patch():
    assert model_prefers_apply_patch("openai", "gpt-5.2")
    assert not model_prefers_apply_patch("openai", "gpt-4o")
    assert not model_prefers_apply_patch("vllm", "Qwen3-8B")


def test_filter_hides_write_for_gpt():
    tools = [
        _tool("sandbox_write_workspace_file"),
        _tool("sandbox_edit_workspace_file"),
        _tool("sandbox_apply_patch"),
        _tool("skill_search"),
    ]
    out = filter_tools_for_model(tools, provider="openai", model_id="gpt-5.2")
    names = {t.name for t in out}
    assert "sandbox_apply_patch" in names
    assert "sandbox_write_workspace_file" not in names
    assert "sandbox_edit_workspace_file" not in names


def test_filter_hides_patch_for_qwen():
    tools = [
        _tool("sandbox_write_workspace_file"),
        _tool("sandbox_apply_patch"),
    ]
    out = filter_tools_for_model(tools, provider="openai", model_id="Qwen3-8B")
    names = {t.name for t in out}
    assert "sandbox_write_workspace_file" in names
    assert "sandbox_apply_patch" not in names
