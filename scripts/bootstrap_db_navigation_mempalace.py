#!/usr/bin/env python3
"""Bootstrap db_navigation_map.md into MemPalace wing_proj_{slug} drawers."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import List, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import src.aion_env  # noqa: F401

from src.memory.project_memory_scope import normalize_nav_room, project_wing
from src.mcp_manager import mcp_manager

_MAX_CHUNK = 480
_NAV_MAP = _REPO / "config_std" / "skills" / "db_navigation_map.md"


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3 :].lstrip()
    return text


def _room_for_section(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ("limitation", "warning", "crucial", "esclusion")):
        return "limitations"
    if any(k in t for k in ("join", "collegament", "relationship", "relazioni")):
        return "join_paths"
    if any(k in t for k in ("entry", "punto", "start", "access")):
        return "entry_points"
    if any(k in t for k in ("guideline", "heuristic", "rule", "mandatory", "agent")):
        return "heuristics"
    if any(k in t for k in ("pitfall", "error", "attenzione")):
        return "pitfalls"
    return "discoveries"


def _chunk_text(text: str, max_len: int = _MAX_CHUNK) -> List[str]:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= max_len:
        return [text] if text else []
    parts: List[str] = []
    buf: List[str] = []
    size = 0
    for para in re.split(r"\n\n+", text):
        para = para.strip()
        if not para:
            continue
        if size + len(para) + 2 > max_len and buf:
            parts.append("\n\n".join(buf))
            buf = [para]
            size = len(para)
        else:
            buf.append(para)
            size += len(para) + 2
    if buf:
        parts.append("\n\n".join(buf))
    out: List[str] = []
    for p in parts:
        if len(p) <= max_len:
            out.append(p)
        else:
            for i in range(0, len(p), max_len):
                out.append(p[i : i + max_len])
    return out


def _parse_sections(body: str) -> List[Tuple[str, str, str]]:
    """Return (title, room, content) per section."""
    sections: List[Tuple[str, str, str]] = []
    current_title = "intro"
    current_lines: List[str] = []

    for line in body.splitlines():
        if line.startswith("## "):
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    room = _room_for_section(current_title)
                    sections.append((current_title, room, content))
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_title, _room_for_section(current_title), content))

    return sections


async def _add_drawer(wing: str, room: str, content: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [dry-run] {wing}/{room} ({len(content)} chars)")
        return True
    async with mcp_manager.session_context("mempalace") as session:
        res = await session.call_tool(
            name="mempalace_add_drawer",
            arguments={
                "wing": wing,
                "room": normalize_nav_room(room),
                "content": content,
                "source_file": "db_navigation_map.md",
                "added_by": "bootstrap_db_navigation",
            },
        )
    text = ""
    if hasattr(res, "content") and res.content:
        text = getattr(res.content[0], "text", str(res.content[0]))
    print(f"  filed {wing}/{room}: {text[:120]}")
    return True


async def run(project_slug: str, dry_run: bool, nav_path: Path) -> int:
    if not nav_path.is_file():
        print(f"Missing navigation map: {nav_path}", file=sys.stderr)
        return 1

    body = _strip_frontmatter(nav_path.read_text(encoding="utf-8"))
    wing = project_wing(project_slug)
    sections = _parse_sections(body)
    total = 0
    print(f"Bootstrap wing={wing} from {nav_path.name} ({len(sections)} sections)")

    for title, room, content in sections:
        header = f"[db_navigation_map — {title}]\n"
        for chunk in _chunk_text(header + content):
            if len(chunk.strip()) < 10:
                continue
            await _add_drawer(wing, room, chunk, dry_run)
            total += 1

    print(f"Done: {total} drawer(s) {'would be ' if dry_run else ''}filed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        default="alibr",
        help="SQL QueryMemory project slug (wing_proj_{slug}); use alibr for db_navigation_map",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print chunks without calling MemPalace MCP",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=_NAV_MAP,
        help="Path to db_navigation_map.md",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.project.strip(), args.dry_run, args.path))


if __name__ == "__main__":
    raise SystemExit(main())
