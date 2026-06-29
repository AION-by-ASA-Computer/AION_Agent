"""
Normalizzazione e pre-validazione argomenti tool MCP prima della chiamata FastMCP.
Evita ValidationError opachi quando il modello omette parametri obbligatori.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

_RESERVED_KEYS = frozenset({"_trace_context"})

_ARG_ALIASES: Dict[str, Dict[str, tuple[str, ...]]] = {
    "query": {
        "sql": ("query", "statement", "q", "text"),
    },
    "sandbox_edit_workspace_file": {
        "relative_path": ("path", "file", "file_path", "filepath", "target_path"),
        "new_string": ("replacement", "replace", "new_text", "new"),
        "old_string": ("old_text", "search", "search_string"),
    },
    "sandbox_write_workspace_file": {
        "relative_path": ("path", "file", "file_path", "filepath", "target_path"),
        "content": ("body", "text", "data"),
    },
    "sandbox_read_text_file": {
        "relative_path": ("path", "file", "file_path", "filepath"),
    },
    "sandbox_run_python_file": {
        "relative_path": ("path", "file", "file_path", "filepath"),
    },
    "sandbox_run_node_file": {
        "relative_path": ("path", "file", "file_path", "filepath"),
    },
    "sandbox_install_npm_packages": {
        "packages": ("package", "package_names", "deps"),
    },
    "save_successful_sql": {
        "sql": ("query", "statement", "q", "text"),
        "project": ("namespace", "drawer", "slug"),
        "request": ("user_request", "question", "prompt"),
    },
    "sql_memory_save": {
        "sql": ("query", "statement", "q", "text"),
        "project": ("namespace", "drawer", "slug"),
        "request": ("user_request", "question", "prompt"),
    },
}

_REQUIRED: Dict[str, tuple[str, ...]] = {
    "sandbox_edit_workspace_file": ("relative_path", "old_string", "new_string"),
    "sandbox_write_workspace_file": ("relative_path", "content"),
    "sandbox_install_npm_packages": ("packages",),
}


def _apply_aliases(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    base = (tool_name or "").split("-")[-1].strip().lower()
    merged_aliases: Dict[str, tuple[str, ...]] = {}
    for key in (tool_name, base):
        part = _ARG_ALIASES.get(key)
        if part:
            merged_aliases.update(part)
    if not merged_aliases:
        return args
    out = dict(args)
    for canonical, alts in merged_aliases.items():
        if _has_value(out.get(canonical)):
            continue
        for alt in alts:
            if alt in out and _has_value(out[alt]):
                out[canonical] = out.pop(alt)
                break
    return out


def _has_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip()) and v.strip() not in ("None", "null", "NULL")
    return True


def normalize_workspace_relative_path(path: str) -> str:
    """Ensure session paths are under workspace/ (models often omit the prefix)."""
    p = (path or "").strip().replace("\\", "/").lstrip("/")
    if not p:
        return p
    while p.startswith("workspace/workspace/"):
        p = p[len("workspace/") :]
    if p.startswith("workspace/"):
        return p
    return f"workspace/{p}"


_WORKSPACE_PATH_TOOLS = frozenset(
    {
        "sandbox_write_workspace_file",
        "sandbox_edit_workspace_file",
        "sandbox_read_text_file",
        "sandbox_run_python_file",
        "sandbox_run_node_file",
    }
)


def _missing_required(tool_name: str, args: Dict[str, Any]) -> list[str]:
    required = _REQUIRED.get(tool_name)
    if not required:
        return []
    missing: list[str] = []
    for key in required:
        if key not in args:
            missing.append(key)
        elif not _has_value(args.get(key)):
            missing.append(key)
    return missing


def _preflight_error(tool_name: str, args: Dict[str, Any], missing: list[str]) -> str:
    hints = {
        "sandbox_edit_workspace_file": (
            "Esempio: relative_path='workspace/script.py', "
            "old_string='vecchio', new_string='nuovo'. "
            "Opzionale: replace_all=true."
        ),
        "sandbox_write_workspace_file": (
            "For NEW HTML/CSS pages prefer markdown artifact protocol (```html with "
            "# artifact_id / # filename metadata) — not this tool. "
            "If you must write: relative_path='workspace/script.py' (workspace/ prefix required)."
        ),
    }
    return json.dumps(
        {
            "ok": False,
            "error": "missing_arguments",
            "tool": tool_name,
            "missing": missing,
            "received_keys": sorted(k for k in args if k not in _RESERVED_KEYS),
            "message": (
                f"{tool_name} richiede i parametri obbligatori: {', '.join(missing)}."
            ),
            "hint": hints.get(tool_name, ""),
        },
        ensure_ascii=False,
    )


def prepare_mcp_tool_arguments(
    tool_name: str, arguments: Optional[Dict[str, Any]]
) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Normalizza alias e verifica parametri obbligatori.

    Returns:
        (clean_arguments, error_json_or_none)
    """
    raw = dict(arguments or {})
    args = {k: v for k, v in raw.items() if k not in _RESERVED_KEYS}
    args = _apply_aliases(tool_name, args)
    if tool_name in _WORKSPACE_PATH_TOOLS and _has_value(args.get("relative_path")):
        before = str(args["relative_path"])
        args["relative_path"] = normalize_workspace_relative_path(before)
    missing = _missing_required(tool_name, args)
    if missing:
        return raw, _preflight_error(tool_name, args, missing)
    # Ripristina chiavi riservate (es. _trace_context) per il downstream.
    for k in _RESERVED_KEYS:
        if k in raw:
            args[k] = raw[k]
    return args, None
