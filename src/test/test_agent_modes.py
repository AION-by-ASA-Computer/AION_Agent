import os
import pytest
from pathlib import Path
from src.main import get_agent


@pytest.mark.anyio
async def test_agent_mode_prompt_injection(monkeypatch, tmp_path):
    # Set up a temporary mock profiles directory
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

    # Mock external runtime dependencies that get_agent executes
    async def dummy_warm_session(*args, **kwargs):
        return None

    monkeypatch.setattr("src.main.mcp_manager.warm_session", dummy_warm_session)

    async def dummy_build_all_tools(*args, **kwargs):
        return []

    monkeypatch.setattr("src.main.build_all_tools", dummy_build_all_tools)

    captured_prompt = None

    # Mock the create_aion_agent factory to capture the system prompt compiled inside get_agent()
    def mock_create_aion_agent(*, chat_generator, tools, system_prompt, **kwargs):
        nonlocal captured_prompt
        captured_prompt = system_prompt

        class MockAgent:
            def __init__(self):
                self.chat_generator = chat_generator
                self.tools = tools
                self.system_prompt = system_prompt

        return MockAgent()

    monkeypatch.setattr("src.main.create_aion_agent", mock_create_aion_agent)

    # Disable the cache to guarantee get_agent fully executes and builds the agent
    monkeypatch.setattr("src.main._AGENT_CACHE_ENABLED", False)

    # 1. Test Plan Mode (explicitly set)
    await get_agent(profile_name="generic_assistant", agent_mode="plan")
    assert "PLAN MODE" in captured_prompt
    assert "Required flow" in captured_prompt
    assert "Minimal research" in captured_prompt
    assert "## Goal" in captured_prompt
    assert "`task_01`" in captured_prompt
    assert "sidebar" in captured_prompt.lower()

    # 2. Test Plan Mode (via plan_mode compatibility flag)
    await get_agent(profile_name="generic_assistant", plan_mode=True)
    assert "PLAN MODE" in captured_prompt

    # 3. Test Ask Mode
    await get_agent(profile_name="generic_assistant", agent_mode="ask")
    assert "ASK MODE" in captured_prompt

    # 4. Test Debug Mode
    await get_agent(profile_name="generic_assistant", agent_mode="debug")
    assert "DEBUG MODE" in captured_prompt

    # 5. Test Normal Mode
    await get_agent(profile_name="generic_assistant", agent_mode="normal")
    assert "PLAN MODE ACTIVE" not in captured_prompt
    assert "ASK MODE" not in captured_prompt
    assert "DEBUG MODE" not in captured_prompt

    # 6. Test environment default mode override (e.g. default is debug, client requests normal)
    monkeypatch.setenv("AION_DEFAULT_AGENT_MODE", "debug")
    await get_agent(profile_name="generic_assistant", agent_mode="normal")
    assert "DEBUG MODE" in captured_prompt


@pytest.mark.anyio
async def test_plan_mode_tool_filtering(monkeypatch, tmp_path):
    """Verifica che in Plan Mode i tool mutanti vengano rimossi fisicamente dalla lista."""
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

    async def dummy_warm_session(*args, **kwargs):
        return None

    monkeypatch.setattr("src.main.mcp_manager.warm_session", dummy_warm_session)

    # Simula una lista di tool che include sia tool mutanti che tool di sola lettura
    class FakeTool:
        def __init__(self, name: str):
            self.name = name

    fake_tools = [
        FakeTool("sandbox_write_workspace_file"),  # mutante — deve essere rimosso
        FakeTool("sandbox_run_python_file"),  # mutante — deve essere rimosso
        FakeTool("sandbox_list_files"),  # lettura — deve restare
        FakeTool("sandbox_read_text_file"),  # lettura — deve restare
        FakeTool("web_search"),  # lettura — deve restare
    ]

    async def dummy_build_all_tools(*args, **kwargs):
        return list(fake_tools)

    monkeypatch.setattr("src.main.build_all_tools", dummy_build_all_tools)

    captured_tools: list = []

    def mock_create_aion_agent(*, chat_generator, tools, system_prompt, **kwargs):
        captured_tools.clear()
        captured_tools.extend(tools)

        class MockAgent:
            def __init__(self):
                self.chat_generator = chat_generator
                self.tools = tools
                self.system_prompt = system_prompt

        return MockAgent()

    monkeypatch.setattr("src.main.create_aion_agent", mock_create_aion_agent)
    monkeypatch.setattr("src.main._AGENT_CACHE_ENABLED", False)

    # Imposta AION_PLAN_MODE_BLOCKED_TOOLS con i tool mutanti
    monkeypatch.setenv(
        "AION_PLAN_MODE_BLOCKED_TOOLS",
        "sandbox_write_workspace_file,sandbox_run_python_file,sandbox_install_python_packages",
    )

    await get_agent(profile_name="generic_assistant", agent_mode="plan")

    tool_names = {t.name for t in captured_tools}

    # I tool mutanti non devono essere presenti
    assert "sandbox_write_workspace_file" not in tool_names
    assert "sandbox_run_python_file" not in tool_names

    # I tool di sola lettura devono essere presenti
    assert "sandbox_list_files" in tool_names
    assert "sandbox_read_text_file" in tool_names
    assert "web_search" in tool_names

    # Normal mode: write tool always removed; run tools stay
    captured_tools.clear()
    await get_agent(profile_name="generic_assistant", agent_mode="normal")
    normal_tool_names = {t.name for t in captured_tools}
    assert "sandbox_write_workspace_file" not in normal_tool_names
    assert "sandbox_run_python_file" in normal_tool_names
