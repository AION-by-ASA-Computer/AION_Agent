"""Token-Oriented Object Notation (TOON) encoder for LLM tool results.

Lightweight subset of https://github.com/toon-format/toon — enough for web tool
payloads without adding a Node dependency. JSON remains available via env.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional


def _collapse_ws(value: Any) -> str:
    """Single-line cell for TOON tabular rows (newlines break line-based parsers)."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _web_search_snippet_cap() -> int:
    try:
        return max(200, int(os.getenv("AION_TOON_WEB_SEARCH_SNIPPET_CHARS", "1200")))
    except ValueError:
        return 1200


def _needs_quotes(value: str) -> bool:
    if not value:
        return True
    if value.strip() != value:
        return True
    if any(c in value for c in (",", ":", "\n", "\r", "\t", '"', "#")):
        return True
    if value[0] in "-#":
        return True
    return False


def _escape_toon_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if _needs_quotes(text):
        return f'"{_escape_toon_string(text)}"'
    return text


def _is_uniform_object_array(rows: List[Any]) -> bool:
    if not rows or not all(isinstance(r, dict) for r in rows):
        return False
    keys = [tuple(sorted(r.keys())) for r in rows]  # type: ignore[union-attr]
    return len(set(keys)) == 1 and bool(keys[0])


def _format_tabular_cell(value: Any) -> str:
    return _format_scalar(_collapse_ws(value))


def _encode_tabular_array(key: str, rows: List[Dict[str, Any]], indent: int) -> str:
    fields = list(rows[0].keys())
    pad = "  " * indent
    header = f"{pad}{key}[{len(rows)}]{{{','.join(fields)}}}:"
    lines = [header]
    for row in rows:
        cells = [_format_tabular_cell(row.get(f, "")) for f in fields]
        lines.append(f"{pad}  {','.join(cells)}")
    return "\n".join(lines)


def encode_toon(data: Any, *, indent: int = 0) -> str:
    """Encode JSON-like data as TOON (lossless for supported shapes)."""
    pad = "  " * indent
    if isinstance(data, dict):
        lines: List[str] = []
        for key, value in data.items():
            k = str(key)
            if isinstance(value, list) and _is_uniform_object_array(value):
                lines.append(_encode_tabular_array(k, value, indent))
            elif isinstance(value, (dict, list)):
                lines.append(f"{pad}{k}:")
                lines.append(encode_toon(value, indent=indent + 1))
            elif isinstance(value, str) and "\n" in value:
                lines.append(f"{pad}{k}: |")
                for line in value.splitlines():
                    lines.append(f"{pad}  {line}")
            else:
                lines.append(f"{pad}{k}: {_format_scalar(value)}")
        return "\n".join(lines)
    if isinstance(data, list):
        if _is_uniform_object_array(data):
            return _encode_tabular_array("items", data, indent - 1 if indent else 0)
        lines = []
        for i, item in enumerate(data):
            lines.append(
                f"{pad}- {_format_scalar(item) if not isinstance(item, (dict, list)) else ''}".rstrip()
            )
            if isinstance(item, (dict, list)):
                lines.append(encode_toon(item, indent=indent + 1))
        return "\n".join(lines)
    return f"{pad}{_format_scalar(data)}"


def format_web_search_toon(data: Dict[str, Any]) -> str:
    """Compact web_search JSON dict → TOON with tabular results."""
    out: Dict[str, Any] = {}
    for key in ("query", "provider_used", "error", "detail"):
        if key in data and data[key]:
            out[key] = data[key]
    rows = data.get("results")
    if isinstance(rows, list):
        slim: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            snippet_cap = _web_search_snippet_cap()
            slim.append(
                {
                    "title": _collapse_ws(row.get("title") or "")[:300],
                    "url": _collapse_ws(row.get("url") or "")[:500],
                    "snippet": _collapse_ws(
                        row.get("snippet") or row.get("content") or ""
                    )[:snippet_cap],
                    "provider": _collapse_ws(row.get("provider") or ""),
                }
            )
        if slim:
            out["results"] = slim
    body = encode_toon(out).strip()
    return f"```toon\n{body}\n```"


def format_web_fetch_toon(data: Dict[str, Any]) -> str:
    """Compact web_fetch JSON dict → TOON (metadata + text block)."""
    meta: Dict[str, Any] = {}
    for key in ("url", "mode", "error", "hint", "chars", "source"):
        if key in data and data[key]:
            meta[key] = data[key]
    text = data.get("text")
    if isinstance(text, str) and text.strip():
        meta["text"] = text
    body = encode_toon(meta).strip()
    return f"```toon\n{body}\n```"


def _parse_toon_scalar(value: str) -> str:
    v = (value or "").strip()
    if v.startswith('"') and v.endswith('"'):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v[1:-1]
    return v


def _strip_toon_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```toon"):
        text = re.sub(r"^```toon\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_web_search_toon(raw: str) -> Optional[Dict[str, Any]]:
    """Parse web_search TOON (subset) back to a JSON-like dict for truncation."""
    text = _strip_toon_fence(raw)
    if not text:
        return None

    out: Dict[str, Any] = {"results": []}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        tab = re.match(r"^results\[(\d+)\]\{([^}]+)\}:$", line.strip())
        if tab:
            fields = [f.strip() for f in tab.group(2).split(",") if f.strip()]
            expected = int(tab.group(1))
            i += 1
            section: List[str] = []
            while i < len(lines):
                line = lines[i]
                trimmed = line.strip()
                if (
                    section
                    and re.match(r"^[a-zA-Z_][\w]*:\s", trimmed)
                    and not line.startswith("  ")
                ):
                    break
                if not section and not line.startswith("  "):
                    break
                section.append(line[2:] if line.startswith("  ") else line)
                parsed = _parse_tabular_rows("\n".join(section), len(fields))
                if len(parsed) >= expected:
                    i += 1
                    break
                i += 1
            rows = [
                {
                    fields[idx]: cells[idx] if idx < len(cells) else ""
                    for idx in range(len(fields))
                }
                for cells in _parse_tabular_rows("\n".join(section), len(fields))
            ]
            out["results"] = rows
            continue
        kv = re.match(r"^([a-zA-Z_][\w]*):\s*(.*)$", line)
        if kv:
            key, val = kv.group(1), kv.group(2)
            if key == "query":
                out["query"] = _parse_toon_scalar(val)
            elif key in ("provider_used", "provider"):
                out["provider_used"] = _parse_toon_scalar(val)
            elif key == "error":
                out["error"] = _parse_toon_scalar(val)
        i += 1
    if not out.get("query") and not out.get("error") and not out.get("results"):
        return None
    return out


def parse_web_fetch_toon(raw: str) -> Optional[Dict[str, Any]]:
    """Parse web_fetch_page TOON back to a JSON-like dict."""
    text = _strip_toon_fence(raw)
    if not text:
        return None

    out: Dict[str, Any] = {}
    scalar_keys = frozenset({"url", "mode", "error", "hint", "source"})
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        kv = re.match(r"^([a-zA-Z_][\w]*):\s*(.*)$", line)
        if kv:
            key, val = kv.group(1), kv.group(2)
            if key == "text" and val.strip() == "|":
                i += 1
                block: List[str] = []
                while i < len(lines) and lines[i].startswith("  "):
                    block.append(lines[i][2:])
                    i += 1
                out["text"] = "\n".join(block)
                continue
            if key == "text":
                out["text"] = _parse_toon_scalar(val)
            elif key == "chars":
                parsed = _parse_toon_scalar(val)
                try:
                    out["chars"] = int(parsed)
                except (TypeError, ValueError):
                    out["chars"] = parsed
            elif key in scalar_keys:
                out[key] = _parse_toon_scalar(val)
        i += 1
    return out or None


def parse_web_tool_payload(raw: str, tool: str) -> Optional[Dict[str, Any]]:
    """Parse web_search / web_fetch_page tool output (TOON or JSON).

    Shared by turn compaction, deep research, and any code that must read
    structured data from native web tool results.
    """
    text = (raw or "").strip()
    if not text:
        return None
    key = (tool or "").strip().lower()
    if text.startswith("```toon"):
        if key == "web_search":
            return parse_web_search_toon(text)
        if key in ("web_fetch_page", "web_fetch"):
            return parse_web_fetch_toon(text)
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _consume_csv_row(buf: str, field_count: int) -> Optional[tuple[List[str], int]]:
    """Parse one tabular TOON row from buf; supports quoted fields spanning newlines."""
    cells: List[str] = []
    cur = ""
    in_quotes = False
    i = 0
    n = len(buf)
    while i < n:
        ch = buf[i]
        if ch == '"':
            if in_quotes and i + 1 < n and buf[i + 1] == '"':
                cur += '"'
                i += 2
                continue
            in_quotes = not in_quotes
            i += 1
            continue
        if ch == "," and not in_quotes:
            cells.append(_parse_toon_scalar(cur))
            cur = ""
            i += 1
            if len(cells) == field_count - 1:
                last = ""
                in_q = False
                while i < n:
                    c = buf[i]
                    if c == '"':
                        if in_q and i + 1 < n and buf[i + 1] == '"':
                            last += '"'
                            i += 2
                            continue
                        in_q = not in_q
                        i += 1
                        continue
                    if c in "\r\n" and not in_q:
                        break
                    last += c
                    i += 1
                cells.append(_parse_toon_scalar(last))
                while i < n and buf[i] in "\r\n":
                    i += 1
                return cells, i
            continue
        cur += ch
        i += 1
    if len(cells) == field_count - 1 and not in_quotes:
        cells.append(_parse_toon_scalar(cur))
        return cells, n
    return None


def _parse_tabular_rows(blob: str, field_count: int) -> List[List[str]]:
    rows: List[List[str]] = []
    pos = 0
    text = blob.strip()
    while pos < len(text):
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if pos >= len(text):
            break
        hit = _consume_csv_row(text[pos:], field_count)
        if not hit:
            break
        cells, consumed = hit
        rows.append(cells)
        pos += consumed
    return rows


def parse_tool_result_payload(
    raw: str, tool: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Parse a native tool result payload when structured access is required."""
    if tool:
        parsed = parse_web_tool_payload(raw, tool)
        if parsed is not None:
            return parsed
    text = (raw or "").strip()
    if not text or text.startswith("```toon"):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
