"""Apply parsed hunks to files on disk."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from .errors import PatchApplyError, PatchParseError
from .parser import (
    AddHunk,
    DeleteHunk,
    Hunk,
    UpdateChunk,
    UpdateHunk,
    parse_patch,
    BEGIN,
    END,
)


def _normalize_unicode(s: str) -> str:
    return (
        s.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2026", "...")
        .replace("\u00a0", " ")
    )


def _try_match(
    lines: List[str], pattern: List[str], start: int, compare, eof: bool
) -> int:
    if eof and pattern:
        from_end = len(lines) - len(pattern)
        if from_end >= start:
            if all(
                compare(lines[from_end + j], pattern[j]) for j in range(len(pattern))
            ):
                return from_end
    for i in range(start, len(lines) - len(pattern) + 1):
        if all(compare(lines[i + j], pattern[j]) for j in range(len(pattern))):
            return i
    return -1


def _seek_sequence(
    lines: List[str], pattern: List[str], start: int, eof: bool = False
) -> int:
    if not pattern:
        return -1
    for compare in (
        lambda a, b: a == b,
        lambda a, b: a.rstrip() == b.rstrip(),
        lambda a, b: a.strip() == b.strip(),
        lambda a, b: _normalize_unicode(a.strip()) == _normalize_unicode(b.strip()),
    ):
        found = _try_match(lines, pattern, start, compare, eof)
        if found != -1:
            return found
    return -1


def _compute_replacements(
    original_lines: List[str], file_path: str, chunks: List[UpdateChunk]
) -> List[Tuple[int, int, List[str]]]:
    replacements: List[Tuple[int, int, List[str]]] = []
    line_index = 0
    for chunk in chunks:
        if chunk.change_context:
            ctx_idx = _seek_sequence(original_lines, [chunk.change_context], line_index)
            if ctx_idx == -1:
                raise PatchApplyError(
                    f"Failed to find context '{chunk.change_context}' in {file_path}"
                )
            line_index = ctx_idx + 1
        if not chunk.old_lines:
            ins = (
                len(original_lines) - 1
                if original_lines and original_lines[-1] == ""
                else len(original_lines)
            )
            replacements.append((ins, 0, chunk.new_lines))
            continue
        pattern = list(chunk.old_lines)
        new_slice = list(chunk.new_lines)
        found = _seek_sequence(
            original_lines, pattern, line_index, chunk.is_end_of_file
        )
        if found == -1 and pattern and pattern[-1] == "":
            pattern = pattern[:-1]
            if new_slice and new_slice[-1] == "":
                new_slice = new_slice[:-1]
            found = _seek_sequence(
                original_lines, pattern, line_index, chunk.is_end_of_file
            )
        if found == -1:
            raise PatchApplyError(
                f"Failed to find expected lines in {file_path}:\n"
                + "\n".join(chunk.old_lines)
            )
        replacements.append((found, len(pattern), new_slice))
        line_index = found + len(pattern)
    replacements.sort(key=lambda x: x[0])
    return replacements


def _apply_replacements(
    lines: List[str], replacements: List[Tuple[int, int, List[str]]]
) -> List[str]:
    result = list(lines)
    for start, old_len, new_seg in reversed(replacements):
        del result[start : start + old_len]
        for j, line in enumerate(new_seg):
            result.insert(start + j, line)
    return result


def derive_new_contents(
    chunks: List[UpdateChunk], original_text: str, file_path: str
) -> str:
    lines = original_text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    new_lines = _apply_replacements(
        lines, _compute_replacements(lines, file_path, chunks)
    )
    if not new_lines or new_lines[-1] != "":
        new_lines.append("")
    return "\n".join(new_lines)


@dataclass
class AppliedFile:
    path: str
    action: str
    move_path: str | None = None


@dataclass
class ApplyResult:
    files: List[AppliedFile]
    summary: str


def _workspace_path(session_root: Path, rel: str) -> Path:
    p = rel.strip().replace("\\", "/").lstrip("/")
    if not p.startswith("workspace/"):
        p = f"workspace/{p}"
    target = (session_root / p).resolve()
    root = (session_root / "workspace").resolve()
    if root not in target.parents and target != root:
        raise PatchApplyError(f"Path escapes workspace: {rel}")
    return target


def apply_patch_text(session_root: Path, patch_text: str) -> ApplyResult:
    if not (patch_text or "").strip():
        raise PatchApplyError("patchText is required")
    normalized = patch_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if normalized == f"{BEGIN}\n{END}":
        raise PatchApplyError("patch rejected: empty patch")
    try:
        hunks = parse_patch(patch_text)
    except PatchParseError as e:
        raise PatchApplyError(f"apply_patch verification failed: {e}") from e
    if not hunks:
        raise PatchApplyError("apply_patch verification failed: no hunks found")

    applied: List[AppliedFile] = []
    for hunk in hunks:
        if isinstance(hunk, AddHunk):
            dest = _workspace_path(session_root, hunk.path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            content = hunk.contents
            if content and not content.endswith("\n"):
                content += "\n"
            dest.write_text(content, encoding="utf-8")
            applied.append(AppliedFile(path=hunk.path, action="add"))
        elif isinstance(hunk, DeleteHunk):
            dest = _workspace_path(session_root, hunk.path)
            if dest.exists():
                dest.unlink()
            applied.append(AppliedFile(path=hunk.path, action="delete"))
        elif isinstance(hunk, UpdateHunk):
            src = _workspace_path(session_root, hunk.path)
            if not src.exists():
                raise PatchApplyError(f"Update target not found: {hunk.path}")
            old = src.read_text(encoding="utf-8")
            new_content = derive_new_contents(hunk.chunks, old, hunk.path)
            if hunk.move_path:
                dst = _workspace_path(session_root, hunk.move_path)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(new_content, encoding="utf-8")
                src.unlink()
                applied.append(
                    AppliedFile(path=hunk.path, action="move", move_path=hunk.move_path)
                )
            else:
                src.write_text(new_content, encoding="utf-8")
                applied.append(AppliedFile(path=hunk.path, action="update"))

    letters = {"add": "A", "update": "M", "delete": "D", "move": "M"}
    parts = []
    for f in applied:
        tag = letters.get(f.action, "M")
        label = f.move_path or f.path
        parts.append(f"{tag} {label}")
    summary = "Success. Updated the following files:\n" + "\n".join(parts)
    return ApplyResult(files=applied, summary=summary)
