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
