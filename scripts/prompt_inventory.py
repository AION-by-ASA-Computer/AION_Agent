#!/usr/bin/env python3
"""Token inventory of a profile prompt. No LLM call.

Prints tokens for profile instructions, each inlined skill, the skill index,
MCP prose, and (with --live) tool schemas grouped by server.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import src.aion_env  # noqa: F401

from src.agent_profile import profile_manager
from src.memory.context_compressor import count_tokens
from src.skill_registry import skill_registry


def _section(title: str, text: str) -> int:
    tokens = count_tokens(text or "")
    print(f"{tokens:6d}  {title}")
    return tokens


def inventory(slug: str, *, live: bool) -> None:
    profile_manager.load_all_if_stale()
    profile = profile_manager.get_profile(slug)
    if profile is None:
        raise SystemExit(f"profilo assente: {slug}")
    print(f"\n== {slug} ==")
    total = 0
    total += _section("istruzioni", profile.instructions or "")
    prompt = profile.generate_system_prompt()
    inlined = set(profile._resolved_critical_skill_names() or [])
    for name in sorted(inlined):
        content = skill_registry.get_skill_full(name) or ""
        total += _section(f"skill inlined:{name}", content)
    index_names = [n for n in (profile.skills or []) if n not in inlined]
    index_bits = []
    summaries = {
        s.get("name"): s for s in skill_registry.list_summaries(allowed_names=index_names)
    }
    for name in index_names:
        meta = summaries.get(name) or {}
        index_bits.append(f"{name} {meta.get('description') or ''}")
    total += _section(f"indice skill ({len(index_names)})", "\n".join(index_bits))
    from src.runtime.mcp_tooling_prompt import build_mcp_tooling_prompt_section
    from src.mcp_manager import mcp_manager
    from src.runtime.tool_exposure import resident_mcp_servers

    prose = build_mcp_tooling_prompt_section(
        resident_mcp_servers(profile.mcp_servers),
        mcp_manager.get_server_config,
    )
    total += _section("prosa MCP residente", prose or "")
    total += _section("system prompt intero", prompt)
    if live:
        total += asyncio.run(_live_tools(profile))
    print(f"{total:6d}  somma sezioni (il system prompt intero è già incluso)")


async def _live_tools(profile) -> int:
    from src.main import build_all_tools
    from src.runtime.tool_exposure import select_resident_tools

    tools = await build_all_tools("inventory", profile, user_id="default")
    tools = select_resident_tools(tools)
    by_server: dict[str, list[str]] = {}
    for tool in tools:
        meta = getattr(tool, "meta", None) or {}
        server = meta.get("mcp_server") or "native"
        by_server.setdefault(server, []).append(tool.name)
    extra = 0
    for server, names in sorted(by_server.items()):
        blob = "\n".join(names)
        extra += _section(f"tool schema gruppo:{server} ({len(names)})", blob)
    return extra


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profiles", nargs="*", default=["generic_assistant", "aion_std"])
    ap.add_argument("--live", action="store_true", help="Avvia i MCP e conta i tool")
    args = ap.parse_args()
    for slug in args.profiles:
        inventory(slug, live=args.live)


if __name__ == "__main__":
    main()
