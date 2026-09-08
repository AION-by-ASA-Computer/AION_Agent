import pytest
from unittest.mock import patch

from src.runtime.wizard_generator import (
    _extract_json_object,
    generate_profile_wizard,
    generate_skill_wizard,
)


def test_extract_json_object_valid():
    text = '```json\n{\n  "name": "test",\n  "slug": "test_slug"\n}\n```'
    parsed = _extract_json_object(text)
    assert parsed == {"name": "test", "slug": "test_slug"}


def test_extract_json_object_with_surrounding_text():
    text = 'Ecco il profilo generato:\n{"name": "agent", "skills": ["core_protocol"]}\nSpero sia utile.'
    parsed = _extract_json_object(text)
    assert parsed == {"name": "agent", "skills": ["core_protocol"]}


def test_extract_json_object_with_think_tags():
    text = '<think>\nSto pensando alla risposta...\n</think>\n```json\n{\n  "name": "think_agent",\n  "slug": "think_slug"\n}\n```'
    parsed = _extract_json_object(text)
    assert parsed == {"name": "think_agent", "slug": "think_slug"}


def test_extract_json_object_truncated_repair():
    text = '```json\n{\n  "name": "Agente Troncato",\n  "slug": "agente_troncato",\n  "description": "Descrizione parziale'
    parsed = _extract_json_object(text)
    assert parsed is not None
    assert parsed["name"] == "Agente Troncato"
    assert parsed["slug"] == "agente_troncato"


@pytest.mark.anyio
async def test_generate_profile_wizard(monkeypatch):
    fake_llm_json = {
        "name": "Supporto Jira & SQL",
        "slug": "supporto_jira_sql",
        "description": "Agente per la gestione ticket e SQL",
        "instructions": "# Role: Support Agent\nHelp the user",
        "skills": ["core_protocol", "artifact_protocol"],
        "mcp_servers": ["session_sandbox"],
    }

    with patch(
        "src.runtime.wizard_generator._call_llm_for_json", return_value=fake_llm_json
    ):
        result = await generate_profile_wizard("Crea un agente per Jira e SQL")
        assert result["name"] == "Supporto Jira & SQL"
        assert result["slug"] == "supporto_jira_sql"
        assert "core_protocol" in result["skills"]
        assert "artifact_protocol" in result["skills"]
        assert "session_sandbox" in result["mcp_servers"]
        assert "skills_hub" in result["mcp_servers"]


@pytest.mark.anyio
async def test_generate_skill_wizard(monkeypatch):
    fake_llm_json = {
        "name": "riconciliazione_fatture",
        "description": "Skill per la riconciliazione fatture",
        "tags": ["finance", "odoo"],
        "status": "draft",
        "content": "---\nname: riconciliazione_fatture\ndescription: Skill per la riconciliazione fatture\ntags: [finance, odoo]\nstatus: draft\n---\n\n# Protocollo\n\n1. Controlla fatture",
    }

    with patch(
        "src.runtime.wizard_generator._call_llm_for_json", return_value=fake_llm_json
    ):
        result = await generate_skill_wizard(
            "Crea una skill per riconciliazione fatture"
        )
        assert result["name"] == "riconciliazione_fatture"
        assert result["tags"] == ["finance", "odoo"]
        assert result["content"].startswith("# Protocollo")


@pytest.mark.anyio
async def test_refine_profile_wizard(monkeypatch):
    current = {
        "name": "Jira Support",
        "slug": "jira_support",
        "description": "Support agent for Jira tickets",
        "instructions": "# Role: Jira Agent",
        "skills": ["core_protocol", "artifact_protocol"],
        "mcp_servers": ["session_sandbox", "skills_hub"],
    }
    fake_refined_llm = {
        "name": "Jira & Email Support Agent",
        "slug": "jira_support",
        "description": "Support agent for Jira and Email",
        "instructions": "# Role: Jira & Email Agent\n\nHandle tickets and emails.",
        "skills": ["core_protocol", "artifact_protocol"],
        "mcp_servers": ["session_sandbox", "skills_hub"],
    }
    from src.runtime.wizard_generator import refine_profile_wizard

    with patch(
        "src.runtime.wizard_generator._call_llm_for_json", return_value=fake_refined_llm
    ):
        res = await refine_profile_wizard("Add email capabilities", current)
        assert res["name"] == "Jira & Email Support Agent"
        assert "core_protocol" in res["skills"]
        assert "session_sandbox" in res["mcp_servers"]


@pytest.mark.anyio
async def test_refine_skill_wizard(monkeypatch):
    current_skill = {
        "name": "riconciliazione_fatture",
        "description": "Skill per riconciliazione",
        "tags": ["finance"],
        "status": "draft",
        "content": "---\nname: riconciliazione_fatture\ndescription: Skill per riconciliazione\ntags: [finance]\nstatus: draft\n---\n\n# Protocollo",
    }
    fake_refined_llm = {
        "name": "riconciliazione_fatture_avanzata",
        "description": "Skill avanzata per riconciliazione fatture ed errori",
        "tags": ["finance", "audit"],
        "status": "draft",
        "content": "---\nname: riconciliazione_fatture_avanzata\ndescription: Skill avanzata per riconciliazione fatture ed errori\ntags: [finance, audit]\nstatus: draft\n---\n\n# Protocollo Avanzato\n\n1. Controlla errori",
    }
    from src.runtime.wizard_generator import refine_skill_wizard

    with patch(
        "src.runtime.wizard_generator._call_llm_for_json", return_value=fake_refined_llm
    ):
        res = await refine_skill_wizard("Aggiungi gestione errori", current_skill)
        assert res["name"] == "riconciliazione_fatture_avanzata"
        assert "audit" in res["tags"]
        assert res["content"].startswith("# Protocollo Avanzato")
