"""
MCP sandbox sessione: elenco file, lettura testo, scrittura workspace, esecuzione Python isolata.
Richiede AION_CHAT_SESSION_ID.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from fastmcp import FastMCP

mcp = FastMCP("AION Session Sandbox")


def _sid() -> str:
    s = os.environ.get("AION_CHAT_SESSION_ID", "").strip()
    if not s:
        raise RuntimeError("AION_CHAT_SESSION_ID not set")
    return s


@mcp.tool()
def sandbox_list_files(subdir: str = "uploads", recursive: bool = False) -> str:
    """List files under uploads/, derived/, workspace/ o unpacked/. Con recursive=True include sottocartelle."""
    import json
    import mimetypes

    from src.session_workspace import SESSION_CONTENT_ROOTS, list_dir, safe_resolve, session_root

    try:
        if not recursive:
            rows = list_dir(_sid(), subdir=subdir)
            return json.dumps(rows, ensure_ascii=False, indent=2)

        root_rel = subdir.strip().replace("\\", "/").strip("/")
        if root_rel == ".":
            root_rel = ""
        if root_rel not in SESSION_CONTENT_ROOTS:
            allowed = ", ".join(sorted(SESSION_CONTENT_ROOTS))
            return f"Error: subdir must be one of: {allowed}"

        sroot = session_root(_sid())
        root = safe_resolve(_sid(), root_rel, must_exist=False)
        rows = []
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if not p.is_file():
                    continue
                if ".versions" in p.parts:
                    continue
                mime, _ = mimetypes.guess_type(p.name)
                rows.append(
                    {
                        "name": p.name,
                        "relative_path": str(p.relative_to(sroot)).replace("\\", "/"),
                        "size_bytes": p.stat().st_size,
                        "mime": mime or "application/octet-stream",
                    }
                )
        return json.dumps(rows, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def sandbox_read_text_file(relative_path: str, max_bytes: int = 500000) -> str:
    """Read a text file under the session (size limit)."""
    from src.session_workspace import safe_resolve

    try:
        p = safe_resolve(_sid(), relative_path, must_exist=True)
    except Exception as e:
        return f"Path error: {e}"
    if not p.is_file():
        return "Not a file."
    if p.stat().st_size > max_bytes:
        return f"File too large (max {max_bytes} bytes)."
    return p.read_text(encoding="utf-8", errors="replace")


@mcp.tool()
def sandbox_get_absolute_path(relative_path: str) -> str:
    """Get the host's absolute path of a session file/directory (uploads/, workspace/, derived/)."""
    from src.session_workspace import safe_resolve
    try:
        p = safe_resolve(_sid(), relative_path, must_exist=False)
        return str(p.absolute())
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def sandbox_write_workspace_file(relative_path: str, content: str) -> str:
    """
    Overwrite a file under the session workspace (path must resolve to workspace/*).

  Do **not** use for new full HTML/CSS landing pages when artifact protocol is active:
  emit a markdown ```html code block with `# artifact_id`, `# title`, `# filename` instead.
    """
    from src.runtime.mcp_tool_args import normalize_workspace_relative_path
    from src.session_workspace import safe_resolve
    try:
        rel = normalize_workspace_relative_path(relative_path)
        if not rel.startswith("workspace/"):
            return (
                "Error: path must be under workspace/ (e.g. workspace/page.html). "
                "For new HTML pages use markdown artifact blocks with # artifact_id / # filename metadata."
            )
        p = safe_resolve(_sid(), rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"File written successfully to {rel}"
    except Exception as e:
        return f"Error while writing: {e}"


@mcp.tool()
def sandbox_edit_workspace_file(
    relative_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """
    Surgical edit of a workspace file: replace old_string with new_string.

    REQUIRED (all three): relative_path, old_string, new_string.
    Optional: replace_all (default false).

    - relative_path: path under workspace/, e.g. workspace/script.py
    - old_string must appear EXACTLY ONCE in the file (default).
    - If it appears multiple times, use replace_all=True to replace all occurrences.
    - The original file is archived in workspace/.versions/ before editing.
    """
    import json

    from src.session_workspace import safe_resolve
    from src.tools.session_fs_tools import EditError, edit_file

    try:
        rel = (relative_path or "").strip().replace("\\", "/").lstrip("/")
        if not rel.startswith("workspace/"):
            return json.dumps(
                {
                    "ok": False,
                    "error": "invalid_path",
                    "message": "sandbox_edit_workspace_file only works on files under workspace/.",
                },
                ensure_ascii=False,
            )

        path = safe_resolve(_sid(), rel, must_exist=True)

        replacements, summary = edit_file(
            path,
            old_string,
            new_string,
            replace_all=replace_all,
        )
        return json.dumps(
            {
                "ok": True,
                "replacements": replacements,
                "file": rel,
                "summary": summary,
            },
            ensure_ascii=False,
        )

    except FileNotFoundError:
        return json.dumps(
            {
                "ok": False,
                "error": "not_found",
                "message": f"File not found: {relative_path}",
            },
            ensure_ascii=False,
        )
    except EditError as e:
        return json.dumps(
            {"ok": False, "error": e.code, "message": str(e)},
            ensure_ascii=False,
        )
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def sandbox_grep_content(
    pattern: str,
    relative_root: str = "workspace",
    fixed_string: bool = False,
    glob_filter: str = "*",
    max_matches: int = 200,
    max_file_bytes: int = 500000,
    max_bytes: int | None = None,
) -> str:
    """Search for a pattern in files under uploads/, workspace/, derived/ o unpacked/."""
    import json
    import re

    from src.session_workspace import SESSION_CONTENT_ROOTS, safe_resolve, session_root
    from src.tools.session_fs_tools import GrepTruncated, grep_content

    try:
        if max_bytes is not None:
            max_file_bytes = max_bytes
        root_rel = (relative_root or "workspace").strip().replace("\\", "/").strip("/")
        if root_rel not in SESSION_CONTENT_ROOTS:
            allowed = ", ".join(sorted(SESSION_CONTENT_ROOTS))
            return json.dumps(
                {
                    "ok": False,
                    "error": "invalid_root",
                    "message": f"relative_root must be one of: {allowed}",
                },
                ensure_ascii=False,
            )

        sroot = session_root(_sid())
        root_path = safe_resolve(_sid(), root_rel, must_exist=False)
        if not root_path.is_dir():
            return json.dumps({"ok": True, "results": [], "count": 0, "truncated": False, "note": "Empty or missing directory"}, ensure_ascii=False)

        results = grep_content(
            sroot,
            root_path,
            pattern,
            fixed_string=fixed_string,
            glob_filter=glob_filter,
            max_matches=max_matches,
            max_file_bytes=max_file_bytes,
        )
        return json.dumps(
            {
                "ok": True,
                "results": results,
                "count": len(results),
                "truncated": False,
            },
            ensure_ascii=False,
        )

    except GrepTruncated as e:
        return json.dumps(
            {
                "ok": True,
                "results": e.results,
                "count": len(e.results),
                "truncated": True,
                "note": f"Results truncated at {len(e.results)} (max_matches). Narrow the pattern.",
            },
            ensure_ascii=False,
        )
    except re.error as e:
        return json.dumps(
            {
                "ok": False,
                "error": "invalid_regex",
                "message": f"Invalid regex pattern: {e}. Use fixed_string=True to search literal text.",
            },
            ensure_ascii=False,
        )
    except ValueError as e:
        return json.dumps({"ok": False, "error": "validation_error", "message": str(e)}, ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def sandbox_fnmatch_glob(
    pattern: str,
    relative_root: str = "workspace",
    max_paths: int = 500,
) -> str:
    """List files matching a glob pattern under the session (uploads/workspace/derived/unpacked)."""
    import json

    from src.session_workspace import SESSION_CONTENT_ROOTS, safe_resolve, session_root
    from src.tools.session_fs_tools import fnmatch_glob

    try:
        root_rel = (relative_root or "workspace").strip().replace("\\", "/").strip("/")
        if root_rel not in SESSION_CONTENT_ROOTS:
            allowed = ", ".join(sorted(SESSION_CONTENT_ROOTS))
            return json.dumps(
                {
                    "ok": False,
                    "error": "invalid_root",
                    "message": f"relative_root must be one of: {allowed}",
                },
                ensure_ascii=False,
            )

        sroot = session_root(_sid())
        root_path = safe_resolve(_sid(), root_rel, must_exist=False)
        if not root_path.is_dir():
            return json.dumps({"ok": True, "paths": [], "count": 0, "truncated": False})

        paths = fnmatch_glob(sroot, root_path, pattern, max_paths=max_paths)
        truncated = any("[TRONCATO" in p for p in paths)
        clean_paths = [p for p in paths if "[TRONCATO" not in p]

        return json.dumps(
            {
                "ok": True,
                "paths": clean_paths,
                "count": len(clean_paths),
                "truncated": truncated,
                "note": f"Pattern: {pattern!r} in {root_rel}/",
            },
            ensure_ascii=False,
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": "validation_error", "message": str(e)}, ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def sandbox_read_file_chunk(
    relative_path: str,
    offset_lines: int = 0,
    max_lines: int = 500,
    max_bytes: int = 0,
) -> str:
    """Read a file chunk by line (large files)."""
    import json

    from src.session_workspace import safe_resolve
    from src.tools.session_fs_tools import read_file_chunk

    try:
        rel = (relative_path or "").strip().replace("\\", "/").lstrip("/")
        path = safe_resolve(_sid(), rel, must_exist=True)

        result = read_file_chunk(
            path,
            offset_lines=max(0, offset_lines),
            max_lines=max(1, max_lines),
            max_bytes=max_bytes if max_bytes > 0 else None,
        )
        result["ok"] = True
        result["file"] = rel
        return json.dumps(result, ensure_ascii=False)

    except FileNotFoundError:
        return json.dumps(
            {"ok": False, "error": "not_found", "message": f"File not found: {relative_path}"},
            ensure_ascii=False,
        )
    except ValueError as e:
        return json.dumps({"ok": False, "error": "validation_error", "message": str(e)}, ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def sandbox_materialize_skill_scripts(skill: str, force: bool = False) -> str:
    """
    Copy a skill package ``scripts/`` tree into this session (for docx/pdf/xlsx/pptx helpers).
    Normally automatic on ``skill_view``; use this to re-sync after server skill updates.
    """
    import json

    from src.tools.skill_materialize import materialize_skill_scripts

    try:
        result = materialize_skill_scripts(_sid(), skill, force=force)
        return json.dumps(result.to_dict(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def sandbox_exec_allowlisted(
    argv: list[str],
    timeout_sec: float = 30.0,
) -> str:
    """
    Run a subprocess only if listed in AION_FS_POLICY_PATH exec.allowlist (requires exec.enabled=true).
    **Not** for running Node/JavaScript files — use ``sandbox_run_node_file``.
    **Not** for npm install — use ``sandbox_install_npm_packages``. Default policy: exec disabled.
    """
    import json

    from src.tools.session_exec import ExecAllowlistError, ExecDeniedError, run_allowlisted

    try:
        if not argv or not isinstance(argv, list):
            return json.dumps(
                {"ok": False, "error": "validation", "message": "argv must be a non-empty list"},
                ensure_ascii=False,
            )

        result = run_allowlisted(_sid(), argv, timeout_sec=timeout_sec)
        return json.dumps(result, ensure_ascii=False)

    except ExecDeniedError as e:
        return json.dumps({"ok": False, "error": "exec_disabled", "message": str(e)}, ensure_ascii=False)
    except ExecAllowlistError as e:
        return json.dumps({"ok": False, "error": "allowlist_denied", "message": str(e)}, ensure_ascii=False)
    except Exception as e:
        return f"Error: {e}"


# @mcp.tool()
def sandbox_execute_python(code: str) -> str:
    """
    [DISABILITATO DEFINITIVAMENTE] - Usa <aion_artifact> con auto_execute="true".
    """
    return "ERROR: This tool is disabled. Usa <aion_artifact identifier='...' type='python' auto_execute='true'> to run code."


@mcp.tool()
def sandbox_install_python_packages(
    packages: list[str],
    use_uv: bool = False,
) -> str:
    """
    Install PyPI packages into the isolated session venv (``data/sessions/<id>/.venv``).
    Abilitato di default (``AION_SANDBOX_ALLOW_PACKAGE_INSTALL=1``). Disabilitato solo se la variabile è ``0``.
    Do not ask the user for manual installs: use this tool.

    - ``packages``: nomi sicuri (es. ``httpx``, ``pandas``, ``httpx[http2]``); no shell/redirezioni.
    - ``use_uv``: se true usa ``uv pip install`` (deve essere sul PATH); altrimenti ``pip`` del venv.
    Variabili utili: ``AION_SANDBOX_PIP_INDEX_URL``, ``AION_SANDBOX_PIP_TIMEOUT_SEC``, ``AION_SANDBOX_PIP_MAX_PACKAGES``,
    ``AION_SANDBOX_BACKEND`` (``subprocess`` dev / ``container`` Podman prod).
    """
    from src.tools.session_venv import install_packages

    try:
        return install_packages(_sid(), packages, use_uv=use_uv)
    except ValueError as e:
        return f"Validation error: {e}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def sandbox_run_python_file(relative_path: str, extra_args: list[str] | None = None) -> str:
    """
    Run ``python -u <relative_path>`` with working directory = session root.
    Uses the **session venv** Python (``.../.venv``) se presente o se ``AION_SANDBOX_AUTO_VENV=1`` (default),
    so packages installed with ``sandbox_install_python_packages``. Otherwise the MCP process interpreter.
    Only accepts paths under ``workspace/*.py``. Extra arguments go in ``extra_args`` (argv dopo lo script).
    No ``result`` field: stdout/stderr and exit code are in the return message.
    """
    from src.tools.session_code import SessionSandboxExecutor

    try:
        return SessionSandboxExecutor(_sid()).run_file(relative_path, extra_args)
    except Exception as e:
        err_msg = str(e)
        if any(h in err_msg.lower() for h in ["not found", "non valido", "no such file"]):
            strategy = os.getenv("AION_ARTIFACT_STRATEGY", "markdown").lower()
            if strategy == "tool":
                hint = "Make sure you called 'sandbox_write_workspace_file' BEFORE running the script."
            elif strategy == "markdown":
                hint = "Make sure you emitted the code in a Markdown block with metadata (artifact_id) BEFORE the tool call."
            else:
                hint = "Make sure you emitted the code using <aion_artifact> in the current response BEFORE the tool call."
            return f"Error: {err_msg}\nHINT: {hint}"
        return f"Error: {err_msg}"


@mcp.tool()
def sandbox_install_npm_packages(
    packages: list[str],
    init_package_json: bool = True,
) -> str:
    """
    Install npm packages into the session workspace (``workspace/node_modules``).
    Does **not** use ``sandbox_exec_allowlisted`` (exec policy may be disabled by default).
    Example: packages=["docx"] then ``sandbox_run_node_file(relative_path="workspace/create_doc.js")``.
    Requires ``AION_SANDBOX_ALLOW_NPM_INSTALL=1`` (default on).
    """
    from src.tools.session_npm import install_npm_packages

    try:
        return install_npm_packages(_sid(), packages, init_if_missing=init_package_json)
    except ValueError as e:
        return f"Validation error: {e}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def sandbox_run_node_file(relative_path: str, extra_args: list[str] | None = None) -> str:
    """
    Run ``node <relative_path>`` with cwd = session root. Accepts only ``workspace/*.js`` (.mjs / .cjs).
    Use for **docx-js** skill. Install deps first with ``sandbox_install_npm_packages(packages=["docx"])``.
    **Do not** use ``sandbox_exec_allowlisted`` to run Node scripts — use this tool.
    For Python use ``sandbox_run_python_file``.
    """
    from src.tools.session_code import SessionSandboxExecutor

    try:
        return SessionSandboxExecutor(_sid()).run_node_file(relative_path, extra_args)
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    import asyncio
    import traceback
    from mcp.server.stdio import stdio_server

    async def main():
        try:
            async with stdio_server() as (read_stream, write_stream):
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(),
                )
        except Exception as e:
            log = os.path.join("data", "mcp_debug.log")
            os.makedirs(os.path.dirname(log) or ".", exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n--- SANDBOX MCP CRASH ---\n{traceback.format_exc()}\n")
            raise e

    asyncio.run(main())
