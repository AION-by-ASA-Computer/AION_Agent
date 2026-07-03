"""Parse OpenCode apply_patch text format."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .errors import PatchParseError

BEGIN = "*** Begin Patch"
END = "*** End Patch"


@dataclass
class UpdateChunk:
    old_lines: List[str] = field(default_factory=list)
    new_lines: List[str] = field(default_factory=list)
    change_context: Optional[str] = None
    is_end_of_file: bool = False


@dataclass
class AddHunk:
    type: str
    path: str
    contents: str = ""


@dataclass
class DeleteHunk:
    type: str
    path: str


@dataclass
class UpdateHunk:
    type: str
    path: str
    move_path: Optional[str] = None
    chunks: List[UpdateChunk] = field(default_factory=list)


Hunk = AddHunk | DeleteHunk | UpdateHunk


def _strip_heredoc(text: str) -> str:
    import re

    m = re.match(
        r"^(?:cat\s+)?<<['\"]?(\w+)['\"]?\s*\n([\s\S]*?)\n\1\s*$", text.strip()
    )
    if m:
        return m.group(2)
    return text


def _parse_header(lines: List[str], i: int):
    line = lines[i]
    if line.startswith("*** Add File:"):
        path = line[len("*** Add File:") :].strip()
        return ("add", path, None, i + 1) if path else None
    if line.startswith("*** Delete File:"):
        path = line[len("*** Delete File:") :].strip()
        return ("delete", path, None, i + 1) if path else None
    if line.startswith("*** Update File:"):
        path = line[len("*** Update File:") :].strip()
        nxt = i + 1
        move = None
        if nxt < len(lines) and lines[nxt].startswith("*** Move to:"):
            move = lines[nxt][len("*** Move to:") :].strip()
            nxt += 1
        return ("update", path, move, nxt) if path else None
    return None


def _parse_add_content(lines: List[str], start: int) -> tuple[str, int]:
    parts: List[str] = []
    i = start
    while i < len(lines) and not lines[i].startswith("***"):
        if lines[i].startswith("+"):
            parts.append(lines[i][1:])
        i += 1
    return "\n".join(parts), i


def _parse_update_chunks(lines: List[str], start: int) -> tuple[List[UpdateChunk], int]:
    chunks: List[UpdateChunk] = []
    i = start
    while i < len(lines) and not lines[i].startswith("***"):
        if lines[i].startswith("@@"):
            ctx = lines[i][2:].strip() or None
            i += 1
            old_lines: List[str] = []
            new_lines: List[str] = []
            eof = False
            while (
                i < len(lines)
                and not lines[i].startswith("@@")
                and not lines[i].startswith("***")
            ):
                cl = lines[i]
                if cl == "*** End of File":
                    eof = True
                    i += 1
                    break
                if cl.startswith(" "):
                    c = cl[1:]
                    old_lines.append(c)
                    new_lines.append(c)
                elif cl.startswith("-"):
                    old_lines.append(cl[1:])
                elif cl.startswith("+"):
                    new_lines.append(cl[1:])
                i += 1
            chunks.append(
                UpdateChunk(
                    old_lines=old_lines,
                    new_lines=new_lines,
                    change_context=ctx,
                    is_end_of_file=eof,
                )
            )
        else:
            i += 1
    return chunks, i


def parse_patch(patch_text: str) -> List[Hunk]:
    cleaned = _strip_heredoc((patch_text or "").strip())
    lines = cleaned.split("\n")
    try:
        begin = next(i for i, ln in enumerate(lines) if ln.strip() == BEGIN)
        end = next(i for i, ln in enumerate(lines) if ln.strip() == END)
    except StopIteration as exc:
        raise PatchParseError(
            "Invalid patch format: missing Begin/End markers"
        ) from exc
    if begin >= end:
        raise PatchParseError("Invalid patch format: Begin must precede End")

    hunks: List[Hunk] = []
    i = begin + 1
    while i < end:
        hdr = _parse_header(lines, i)
        if not hdr:
            i += 1
            continue
        kind, path, move, nxt = hdr
        if kind == "add":
            content, nxt2 = _parse_add_content(lines, nxt)
            hunks.append(AddHunk(type="add", path=path, contents=content))
            i = nxt2
        elif kind == "delete":
            hunks.append(DeleteHunk(type="delete", path=path))
            i = nxt
        else:
            chunks, nxt2 = _parse_update_chunks(lines, nxt)
            hunks.append(
                UpdateHunk(type="update", path=path, move_path=move, chunks=chunks)
            )
            i = nxt2
    return hunks
