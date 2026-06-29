"""Lettura file installati di un server MCP (README, .env.example, sorgenti) per discovery e advise."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger("aion.mcp_server_files")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_mcp_server_dir(slug: str) -> Path | None:
    """Directory del server in mcp_servers/<slug> (match esatto o parziale)."""
    repo_root = _repo_root()
    mcp_dir = repo_root / "mcp_servers" / slug
    if mcp_dir.is_dir():
        return mcp_dir
    servers_root = repo_root / "mcp_servers"
    if not servers_root.is_dir():
        return None
    norm = slug.replace("-", "").replace("_", "").lower()
    for d in sorted(servers_root.iterdir()):
        if d.is_dir() and norm in d.name.replace("-", "").replace("_", "").lower():
            return d
    return None


def read_mcp_server_files(slug: str, *, max_total: int = 5000) -> str:
    """Contesto testuale per LLM advise / discovery (markdown con sezioni)."""
    mcp_dir = resolve_mcp_server_dir(slug)
    if not mcp_dir:
        return ""

    parts: List[str] = []
    total = 0

    readme = mcp_dir / "README.md"
    if readme.is_file():
        content = readme.read_text(encoding="utf-8", errors="replace")
        if len(content) > 4000:
            content = content[:4000] + "\n... (truncated)"
        parts.append(f"### README.md\n```markdown\n{content}\n```")
        total += len(content)

    for env_name in (".env.example", ".env.sample", ".env.template", ".env"):
        env_file = mcp_dir / env_name
        if env_file.is_file() and total < max_total:
            content = env_file.read_text(encoding="utf-8", errors="replace")
            if len(content) > 1500:
                content = content[:1500] + "\n... (truncated)"
            parts.append(f"### {env_name}\n```\n{content}\n```")
            total += len(content)
            break

    pkg = mcp_dir / "package.json"
    if pkg.is_file() and total < max_total:
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            relevant = {
                k: data[k]
                for k in ("name", "version", "description", "dependencies", "scripts")
                if k in data
            }
            if "dependencies" in relevant:
                relevant["dependencies"] = list(relevant["dependencies"].keys())
            content = json.dumps(relevant, indent=2, ensure_ascii=False)
            parts.append(f"### package.json\n```json\n{content}\n```")
            total += len(content)
        except Exception:
            pass

    for src_name in (
        "index.ts",
        "index.js",
        "server.ts",
        "server.py",
        "main.ts",
        "main.py",
        "src/index.ts",
        "src/index.js",
    ):
        src_file = mcp_dir / src_name
        if not src_file.is_file() or total >= max_total:
            continue
        content = src_file.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        relevant_lines: List[str] = []
        for line in lines:
            low = line.lower()
            if any(
                kw in low
                for kw in (
                    "process.env",
                    "dotenv",
                    "environ",
                    "imap",
                    "smtp",
                    "email",
                    "api_key",
                    "access_token",
                    "client_id",
                    "client_secret",
                    "password",
                    "z.object",
                    "z.string",
                    "parse(process.env",
                    "getenv",
                )
            ):
                if len(line) > 220:
                    line = line[:220] + "..."
                relevant_lines.append(line)
        if relevant_lines:
            snippet = "\n".join(relevant_lines[:100])
            if len(relevant_lines) > 100:
                snippet += f"\n... ({len(relevant_lines) - 100} altre linee)"
            parts.append(f"### {src_name} (estratti)\n```\n{snippet}\n```")
            total += len(snippet)
        break

    logger.debug("read_mcp_server_files %s: %d chars", slug, total)
    return "\n".join(parts) if parts else ""
