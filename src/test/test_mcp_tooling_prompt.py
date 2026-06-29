import src.runtime.mcp_tooling_prompt as mtp
from src.runtime.mcp_tooling_prompt import build_mcp_tooling_prompt_section


def test_build_mcp_tooling_prompt_includes_clickup_guidance(monkeypatch):
    catalog_clickup = {
        "connectors": [
            {
                "id": "clickup",
                "title": "ClickUp",
                "agent_guidance": "USA I TOOL TASK PER CREARE.",
                "mcp_upstream_docs_url": "https://example.com/docs",
            }
        ]
    }

    def fake_get(name: str):
        if name == "my_clickup":
            return {"aion_connector_id": "clickup"}
        return {}

    monkeypatch.setattr(mtp, "load_mcp_connector_catalog", lambda: catalog_clickup)
    text = build_mcp_tooling_prompt_section(["my_clickup"], fake_get)

    assert "USA I TOOL TASK" in text
    assert "https://example.com/docs" in text
    assert "list_tools" in text


def test_build_mcp_tooling_prompt_empty_without_guidance(monkeypatch):
    catalog_no_guidance = {"connectors": [{"id": "clickup", "title": "ClickUp"}]}

    def fake_get(_: str):
        return {"aion_connector_id": "clickup"}

    monkeypatch.setattr(mtp, "load_mcp_connector_catalog", lambda: catalog_no_guidance)
    text = build_mcp_tooling_prompt_section(["srv"], fake_get)
    assert text == ""
