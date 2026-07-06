"""
Early SSE preview for filesystem write tools (OpenCode-style).

Emits artifact_start + chunked artifact_content on tool_start so chat-ui can show
"Generating script…" and stream the payload while MCP executes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

from src.runtime.mcp_tool_args import default_write_relative_path

FILE_PREVIEW_TOOLS = frozenset(
    {
        "sandbox_write_workspace_file",
        "sandbox_edit_workspace_file",
        "sandbox_apply_patch",
    }
)

_PREVIEW_CHUNK = 6000


def is_file_preview_tool(tool_name: str) -> bool:
    base = (tool_name or "").split("-")[-1].strip().lower()
    return base in FILE_PREVIEW_TOOLS


def artifact_type_for_path(relative_path: str) -> str:
    p = (relative_path or "").lower()
    if p.endswith(".html"):
        return "html"
    if p.endswith(".py"):
        return "python"
    if p.endswith(".js"):
        return "javascript"
    if p.endswith((".md", ".markdown")):
        return "markdown"
    return "text"


def artifact_id_for_path(relative_path: str, *, suffix: str = "") -> str:
    aid = (relative_path or "workspace/file.txt").replace("/", "_").replace(".", "_")
    return f"{aid}{suffix}" if suffix else aid


def _chunk_text(text: str, size: int = _PREVIEW_CHUNK) -> List[str]:
    if not text:
        return []
    if len(text) <= size:
        return [text]
    return [text[i : i + size] for i in range(0, len(text), size)]


def build_file_tool_preview_events(
    tool_name: str,
    args: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Returns (sse_events, pending_metadata) for pending_write_artifacts storage.
    """
    base = (tool_name or "").split("-")[-1].strip().lower()
    args = dict(args or {})
    events: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"preview_emitted": False}

    if base == "sandbox_write_workspace_file":
        content = str(args.get("content") or "")
        rp = str(args.get("relative_path") or "").strip()
        if not rp and content.strip():
            rp = default_write_relative_path(content)
        elif not rp:
            rp = "workspace/file.txt"
        aid = artifact_id_for_path(rp)
        a_type = artifact_type_for_path(rp)
        title = Path(rp).name or rp
        meta.update(
            {
                "content": content,
                "mode": "write",
                "relative_path": rp,
                "artifact_id": aid,
            }
        )
        if not content.strip():
            return events, meta
        events.append(
            {
                "type": "artifact_start",
                "artifact": {
                    "identifier": aid,
                    "type": a_type,
                    "title": title,
                    "filename": title,
                    "pending": True,
                    "source": "tool",
                    "auto_execute": False,
                },
            }
        )
        for piece in _chunk_text(content):
            events.append(
                {"type": "artifact_content", "content": piece, "artifact_id": aid}
            )
        meta["preview_emitted"] = True
        return events, meta

    if base == "sandbox_edit_workspace_file":
        rp = str(args.get("relative_path") or "workspace/file.txt")
        aid = artifact_id_for_path(rp, suffix="_edit")
        a_type = artifact_type_for_path(rp)
        title = Path(rp).name or rp
        preview = str(args.get("new_string") or "")
        meta.update(
            {
                "old_string": str(args.get("old_string") or ""),
                "new_string": preview,
                "mode": "edit",
                "relative_path": rp,
                "artifact_id": aid,
            }
        )
        if not preview.strip():
            return events, meta
        events.append(
            {
                "type": "artifact_start",
                "artifact": {
                    "identifier": aid,
                    "type": a_type,
                    "title": f"Edit: {title}",
                    "pending": True,
                    "source": "tool",
                    "auto_execute": False,
                },
            }
        )
        for piece in _chunk_text(preview):
            events.append(
                {"type": "artifact_content", "content": piece, "artifact_id": aid}
            )
        meta["preview_emitted"] = True
        return events, meta

    if base == "sandbox_apply_patch":
        patch_text = str(args.get("patch_text") or "")
        aid = artifact_id_for_path("__patch__", suffix="_patch")
        meta.update({"patch_text": patch_text, "mode": "patch", "artifact_id": aid})
        if not patch_text.strip():
            return events, meta
        events.append(
            {
                "type": "artifact_start",
                "artifact": {
                    "identifier": aid,
                    "type": "text",
                    "title": "Patch",
                    "mode": "patch",
                    "pending": True,
                    "source": "tool",
                    "auto_execute": False,
                },
            }
        )
        for piece in _chunk_text(patch_text):
            events.append(
                {"type": "artifact_content", "content": piece, "artifact_id": aid}
            )
        meta["preview_emitted"] = True
        return events, meta

    return events, meta


def iter_preview_events(
    tool_name: str, args: Dict[str, Any]
) -> Iterator[Dict[str, Any]]:
    events, _ = build_file_tool_preview_events(tool_name, args)
    yield from events
