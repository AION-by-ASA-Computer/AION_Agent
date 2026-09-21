"""Tests for LLM-assisted MCP schema enrichment and fallback."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.mcp_llm_enricher import _clean_json_response, enrich_mcp_schema_with_llm


def test_clean_json_response() -> None:
    raw_markdown = """```json
{
  "display_name": "Email Server",
  "description": "Integration for IMAP/SMTP",
  "fields": [
    {"key": "EMAIL_USER", "label": "Email", "type": "text"}
  ]
}
```"""
    cleaned = _clean_json_response(raw_markdown)
    parsed = json.loads(cleaned)
    assert parsed["display_name"] == "Email Server"
    assert len(parsed["fields"]) == 1


@pytest.mark.anyio
async def test_llm_enrichment_fallback_when_llm_fails() -> None:
    # When LLM raises an exception or is unavailable, it should fall back to static rules seamlessly
    with patch(
        "src.runtime.llm_adapter.resolve_llm_credentials",
        side_effect=ValueError("No LLM provider configured"),
    ):
        result = await enrich_mcp_schema_with_llm(
            "email-mcp",
            {
                "env": {
                    "EMAIL_USER": "${AION_USER_EMAIL_MCP__EMAIL_USER}",
                    "PASSWORD": "${AION_USER_EMAIL_MCP__PASSWORD}",
                    "USE_SSL": "${AION_USER_EMAIL_MCP__USE_SSL}",
                }
            },
        )
        assert result["enriched_by"] == "static_rules"
        assert result["credential_mode"] == "per_user"
        keys = {f["key"] for f in result["credential_schema"]}
        assert "EMAIL_USER" in keys
        assert "PASSWORD" in keys
        assert "USE_SSL" in keys


@pytest.mark.anyio
async def test_llm_enrichment_success_merges_fields() -> None:
    mock_llm_response = {
        "display_name": "Google / Office 365 Email",
        "description": "Invia e ricevi email aziendali tramite IMAP e SMTP protetti.",
        "credential_mode": "per_user",
        "fields": [
            {
                "key": "EMAIL_USER",
                "label": "Indirizzo Email Aziendale",
                "description": "Inserisci il tuo indirizzo email di lavoro completo",
                "type": "text",
                "category": "basic",
                "required": True,
            },
            {
                "key": "PASSWORD",
                "label": "Password Applicativa",
                "description": "Genera una password per le app nelle impostazioni di sicurezza Google/Microsoft",
                "type": "password",
                "category": "basic",
                "required": True,
            },
            {
                "key": "IMAP_HOST",
                "label": "Server IMAP",
                "description": "Server per la ricezione della posta",
                "type": "text",
                "category": "advanced",
                "required": False,
                "default_value": "imap.gmail.com",
            },
        ],
    }

    mock_choice = AsyncMock()
    mock_choice.message.content = json.dumps(mock_llm_response)
    mock_completion = AsyncMock()
    mock_completion.choices = [mock_choice]

    with patch(
        "src.runtime.llm_adapter.resolve_llm_credentials",
        return_value=("http://localhost:8000/v1", "openai/gpt-4o", "dummy-key"),
    ):
        with patch("litellm.acompletion", return_value=mock_completion):
            result = await enrich_mcp_schema_with_llm(
                "email-mcp",
                {
                    "env": {
                        "EMAIL_USER": "${AION_USER_EMAIL_MCP__EMAIL_USER}",
                        "PASSWORD": "${AION_USER_EMAIL_MCP__PASSWORD}",
                    }
                },
            )
            assert result["enriched_by"] == "llm"
            assert result["display_name"] == "Google / Office 365 Email"
            assert (
                result["description"]
                == "Invia e ricevi email aziendali tramite IMAP e SMTP protetti."
            )
            by_key = {f["key"]: f for f in result["credential_schema"]}
            assert by_key["EMAIL_USER"]["label"] == "Indirizzo Email Aziendale"
            assert by_key["PASSWORD"]["label"] == "Password Applicativa"
            assert by_key["IMAP_HOST"]["category"] == "advanced"
