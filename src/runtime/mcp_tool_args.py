"""
Normalizzazione e pre-validazione argomenti tool MCP prima della chiamata FastMCP.
Evita ValidationError opachi quando il modello omette parametri obbligatori.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("aion.mcp_tool_args")

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
    "sandbox_apply_patch": {
        "patch_text": ("patch", "patchText", "diff", "content"),
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
    "sandbox_apply_patch": ("patch_text",),
    "sandbox_install_npm_packages": ("packages",),
    "sandbox_run_python_file": ("relative_path",),
    "sandbox_run_node_file": ("relative_path",),
    "sandbox_read_text_file": ("relative_path",),
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
    if p.startswith(("workspace/", "uploads/", "derived/", "unpacked/")):
        return p
    return f"workspace/{p}"


_WORKSPACE_PATH_TOOLS = frozenset(
    {
        "sandbox_write_workspace_file",
        "sandbox_edit_workspace_file",
        "sandbox_read_text_file",
        "sandbox_run_python_file",
        "sandbox_run_node_file",
        "sandbox_apply_patch",
    }
)


def _required_keys(tool_name: str) -> tuple[str, ...]:
    base = (tool_name or "").split("-")[-1].strip().lower()
    return _REQUIRED.get(tool_name) or _REQUIRED.get(base) or ()


def tool_has_required_fields(tool_name: str) -> bool:
    return bool(_required_keys(tool_name))


def missing_required_fields(tool_name: str, args: Dict[str, Any]) -> list[str]:
    return _missing_required(tool_name, args)


def default_write_relative_path(content: str) -> str:
    """Infer workspace path when vLLM/Qwen omits relative_path but sends content."""
    c = (content or "").lstrip()
    if "require('docx')" in c or 'require("docx")' in c or "from 'docx'" in c:
        return "workspace/create_doc.js"
    if c.startswith("#!/usr/bin/env node") or "require(" in c[:500]:
        return "workspace/script.js"
    if c.startswith("import ") or "def " in c[:200]:
        return "workspace/script.py"
    return "workspace/file.txt"


def _missing_required(tool_name: str, args: Dict[str, Any]) -> list[str]:
    required = _required_keys(tool_name)
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
            "Example: relative_path='workspace/script.js', content='full file body'. "
            "Prefer sandbox_edit_workspace_file when the file already exists. "
            "If arguments were empty, vLLM/Qwen may have truncated tool JSON to '{' only — "
            "retry with a MINIMAL script (<60 lines) or lower reasoning effort."
        ),
        "sandbox_apply_patch": (
            "Example: patch_text with *** Begin Patch ... *** End Patch envelope."
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

    # Automatically resolve save_path for download_attachment to the session sandbox
    t_name = tool_name.lower().replace("-", "_")
    if (
        t_name == "download_attachment" or t_name.endswith("_download_attachment")
    ) and "save_path" in args:
        val = args["save_path"]
        if isinstance(val, str):
            cleaned = val.strip().replace("\\", "/").lstrip("/")
            import re

            for prefix in (
                "app/data/sessions/[^/]+/",
                "app/",
                "workspace/workspace/",
                "workspace/",
            ):
                cleaned = re.sub("^" + prefix, "", cleaned)
            cleaned = cleaned.lstrip("/")
            if "/" not in cleaned:
                cleaned = f"uploads/{cleaned}"
            elif not cleaned.startswith(
                ("uploads/", "workspace/", "derived/", "unpacked/")
            ):
                cleaned = f"uploads/{cleaned}"

            from src.runtime.context import get_current_session_id
            from src.session_workspace import safe_resolve

            sid = get_current_session_id()
            if sid and sid != "default":
                try:
                    resolved = safe_resolve(sid, cleaned, must_exist=False)
                    args["save_path"] = str(resolved.absolute())
                except Exception:
                    pass

    base_tool = (tool_name or "").split("-")[-1].strip().lower()
    if base_tool == "sandbox_write_workspace_file" and _has_value(args.get("content")):
        if not _has_value(args.get("relative_path")):
            inferred = default_write_relative_path(str(args.get("content") or ""))
            args["relative_path"] = inferred
            logger.warning(
                "write_tool_inferred_relative_path path=%s content_len=%d",
                inferred,
                len(str(args.get("content") or "")),
            )

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


_RUN_FILE_TOOLS = frozenset({"sandbox_run_node_file", "sandbox_run_python_file"})
_RUN_FILE_EXT = {
    "sandbox_run_node_file": ".js",
    "sandbox_run_python_file": ".py",
}


def preflight_run_file_tool(
    tool_name: str, args: Dict[str, Any], session_id: str
) -> Optional[str]:
    """OpenCode-style gate: script must exist, be non-empty, and have a valid extension."""
    base = (tool_name or "").split("-")[-1].strip().lower()
    if base not in _RUN_FILE_TOOLS:
        return None
    rel = str(args.get("relative_path") or "").strip()
    if not rel:
        return None
    expected_ext = _RUN_FILE_EXT[base]
    if not rel.lower().endswith(expected_ext):
        return json.dumps(
            {
                "ok": False,
                "error": "invalid_extension",
                "tool": tool_name,
                "message": (
                    f"{tool_name} requires a {expected_ext} file under workspace/. "
                    "Create the script with sandbox_write_workspace_file first."
                ),
            },
            ensure_ascii=False,
        )
    sid = (session_id or "").strip()
    if not sid or sid == "default":
        return None
    try:
        from src.session_workspace import safe_resolve

        path = safe_resolve(sid, rel, must_exist=True)
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "error": "file_not_found",
                "tool": tool_name,
                "relative_path": rel,
                "message": (
                    f"File not found: {rel}. "
                    "Use sandbox_write_workspace_file to create it before running."
                ),
                "detail": str(exc)[:200],
            },
            ensure_ascii=False,
        )
    try:
        if not path.is_file():
            raise FileNotFoundError(rel)
        size = path.stat().st_size
    except OSError as exc:
        return json.dumps(
            {
                "ok": False,
                "error": "file_not_readable",
                "tool": tool_name,
                "message": f"Cannot read {rel}: {exc}",
            },
            ensure_ascii=False,
        )
    if size <= 0:
        return json.dumps(
            {
                "ok": False,
                "error": "empty_file",
                "tool": tool_name,
                "relative_path": rel,
                "message": (
                    f"{rel} is empty. Write complete script content with "
                    "sandbox_write_workspace_file, then retry."
                ),
            },
            ensure_ascii=False,
        )
    return None
