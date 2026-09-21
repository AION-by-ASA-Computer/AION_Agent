"""Tests for automatic MCP credential discovery."""

from pathlib import Path

from src.mcp_credential_discovery import discover_mcp_credentials


def test_discover_env_from_readme_snippet(tmp_path: Path, monkeypatch) -> None:
    mcp_dir = tmp_path / "mcp_servers" / "email-mcp"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "README.md").write_text(
        """
## Single-account via environment variables
```json
{
  "env": {
    "MCP_EMAIL_ADDRESS": "you@gmail.com",
    "MCP_EMAIL_PASSWORD": "secret",
    "MCP_EMAIL_IMAP_HOST": "imap.gmail.com",
    "MCP_EMAIL_SMTP_HOST": "smtp.gmail.com"
  }
}
```
Also stores settings in ~/.config/email-mcp/config.toml
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.mcp_server_files._repo_root", lambda: tmp_path)
    result = discover_mcp_credentials("email-mcp", {"env": {"NODE_ENV": "production"}})
    assert result.has_env_auth
    assert result.credential_mode_hint == "per_user"
    assert "MCP_EMAIL_ADDRESS" in result.env_keys
    assert "MCP_EMAIL_PASSWORD" in result.env_keys


def test_discover_gabigabu_style_from_source(tmp_path: Path, monkeypatch) -> None:
    mcp_dir = tmp_path / "mcp_servers" / "email-mcp-server"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "index.ts").write_text(
        """
import { z } from 'zod';
const env = z.object({
  EMAIL_USER: z.string().email(),
  EMAIL_PASSWORD: z.string().min(1),
  IMAP_HOST: z.string().min(1),
  IMAP_PORT: z.string().regex(/^\\d+$/),
}).parse(process.env);
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.mcp_server_files._repo_root", lambda: tmp_path)
    result = discover_mcp_credentials("email-mcp-server", {})
    assert "EMAIL_USER" in result.env_keys
    assert "IMAP_HOST" in result.env_keys
    assert result.credential_mode_hint == "per_user"


def test_discover_custom_aion_variables(tmp_path: Path, monkeypatch) -> None:
    mcp_dir = tmp_path / "mcp_servers" / "custom-aion-mcp"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "index.ts").write_text(
        """
import { z } from 'zod';
const env = z.object({
  AION_MY_CUSTOM_SECRET: z.string(),
  AION_CHAT_SESSION_ID: z.string(),
}).parse(process.env);
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.mcp_server_files._repo_root", lambda: tmp_path)
    result = discover_mcp_credentials("custom-aion-mcp", {})
    assert "AION_MY_CUSTOM_SECRET" in result.env_keys
    assert "AION_CHAT_SESSION_ID" not in result.env_keys


def test_semantic_field_classification_and_categories() -> None:
    from src.mcp_credential_discovery import (
        _field_category,
        _field_type,
        _schema_from_keys,
    )

    assert _field_type("EMAIL_PASSWORD") == "password"
    assert _field_type("ENABLE_ATTACHMENT_DOWNLOAD") == "boolean"
    assert _field_type("USE_SSL") == "boolean"
    assert _field_type("IMAP_HOST") == "text"
    assert _field_type("API_KEY") == "password"

    assert _field_category("EMAIL_USER") == "basic"
    assert _field_category("PASSWORD") == "basic"
    assert _field_category("API_KEY") == "basic"
    assert _field_category("IMAP_HOST") == "advanced"
    assert _field_category("IMAP_PORT") == "advanced"
    assert _field_category("ENABLE_ATTACHMENT_DOWNLOAD") == "advanced"

    schema = _schema_from_keys(
        ["EMAIL_USER", "PASSWORD", "IMAP_HOST", "ENABLE_ATTACHMENT_DOWNLOAD"],
        defaults={"ENABLE_ATTACHMENT_DOWNLOAD": "true"},
    )
    by_key = {s["key"]: s for s in schema}
    assert by_key["EMAIL_USER"]["category"] == "basic"
    assert by_key["EMAIL_USER"]["type"] == "text"
    assert by_key["EMAIL_USER"]["label"] == "Nome Utente / Email"

    assert by_key["PASSWORD"]["category"] == "basic"
    assert by_key["PASSWORD"]["type"] == "password"
    assert by_key["PASSWORD"]["required"] is True

    assert by_key["ENABLE_ATTACHMENT_DOWNLOAD"]["category"] == "advanced"
    assert by_key["ENABLE_ATTACHMENT_DOWNLOAD"]["type"] == "boolean"
    assert by_key["ENABLE_ATTACHMENT_DOWNLOAD"]["required"] is False
    assert by_key["ENABLE_ATTACHMENT_DOWNLOAD"]["label"] == "Scarica Allegati"


def test_static_org_env_omitted_from_schema(tmp_path: Path, monkeypatch) -> None:
    mcp_dir = tmp_path / "mcp_servers" / "email-org-test"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "index.ts").write_text(
        """
const env = {
  EMAIL_USER: process.env.EMAIL_USER,
  PASSWORD: process.env.PASSWORD,
  IMAP_HOST: process.env.IMAP_HOST,
  IMAP_PORT: process.env.IMAP_PORT,
};
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.mcp_server_files._repo_root", lambda: tmp_path)
    # Admin configured IMAP_HOST statically at org level
    cfg = {
        "env": {
            "EMAIL_USER": "${AION_USER_EMAIL_ORG_TEST__EMAIL_USER}",
            "PASSWORD": "${AION_USER_EMAIL_ORG_TEST__PASSWORD}",
            "IMAP_HOST": "imap.corp.local",  # static literal!
        }
    }
    result = discover_mcp_credentials("email-org-test", cfg)
    schema_keys = {s["key"] for s in result.schema}
    assert "EMAIL_USER" in schema_keys
    assert "PASSWORD" in schema_keys
    assert "IMAP_HOST" not in schema_keys  # omitted because it's static org config!
