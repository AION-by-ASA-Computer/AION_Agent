#!/usr/bin/env python3
"""
AION Agent Smoke Tests Runner.

Orchestrates test cases defined in test_config.json against the AION Agent (Generic Assistant),
intercepts internal streams (reasoning, MCP/sandbox tool calls with parameters, and final output),
and generates a structured Markdown report in the outputs directory.

Supports:
- CLI standalone execution (sequential)
- Clean, readable real-time terminal feedback without internal DB spam
- Programmatic async streaming for FastAPI SSE endpoints
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

# Ensure UTF-8 output encoding in Windows terminal
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure repo root is in sys.path when running as a standalone script
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Silence noisy OTEL warning if exporter is not configured
if (
    not os.environ.get("OTEL_LOGS_EXPORTER")
    or os.environ.get("OTEL_LOGS_EXPORTER") == "otlp"
):
    os.environ["OTEL_LOGS_EXPORTER"] = "none"

# MUST be first import to load .env correctly
import src.aion_env  # noqa: F401

from evals.agent_smoke_tests.evaluator import evaluate_test
from src.agent_pipeline import AgentPipeline
from src.main import get_agent, set_event_loop
from src.session_workspace import ensure_session_dirs, save_upload, session_root

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "test_config.json"
DEFAULT_OUTPUTS_DIR = SCRIPT_DIR / "outputs"
ASSETS_DIR = SCRIPT_DIR / "assets"

logger = logging.getLogger("aion.smoke_tests")


def mute_internal_loggers():
    """Mute noisy database, persistence, and internal pipeline loggers so CLI output is clean."""
    noisy = [
        "aion.stream_sync",
        "src.runtime.turn.turn_persistence",
        "src.runtime.stream_loop",
        "aion.pipeline",
        "aion.api",
        "aion.tool_events",
        "sqlalchemy",
        "sqlalchemy.engine",
        "aiosqlite",
        "sse_starlette",
        "urllib3",
        "httpcore",
        "httpx",
        "openai",
        "opik",
        "haystack",
        "haystack.dataclasses",
    ]
    for name in noisy:
        lg = logging.getLogger(name)
        lg.setLevel(logging.ERROR)
        lg.propagate = False


async def ensure_db_ready():
    """Initialize DB schema and migrations so SQLite foreign keys and columns exist."""
    try:
        from src.data.engine import init_engine
        from src.data.bootstrap import ensure_bootstrap_schema
        from src.data.migrations import run_migrations

        eng = init_engine()
        await ensure_bootstrap_schema(eng)
        run_migrations()
    except Exception:
        pass


SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _is_safe_path(target: Path | str, allowed_bases: List[Path | str]) -> bool:
    """Verifies that a resolved target path resides strictly within one of the allowed base directories."""
    try:
        t_res = Path(target).resolve()
        for base in allowed_bases:
            b_res = Path(base).resolve()
            if t_res.is_relative_to(b_res):
                return True
    except Exception:
        return False
    return False


def resolve_asset_path(rel_path: str) -> Optional[Path]:
    """Resolve an asset file path relative to SCRIPT_DIR or ASSETS_DIR with fallback, preventing path traversal."""
    if not rel_path or "\x00" in rel_path:
        return None

    clean = rel_path.strip().replace("\\", "/").lstrip("/")
    if ".." in clean or clean.startswith(("/", "\\")):
        return None

    p = Path(clean)
    candidates = [
        SCRIPT_DIR / clean,
        ASSETS_DIR / p.name,
        REPO_ROOT / clean,
    ]
    # Check fallback names for known assets
    base_name = p.name.lower()
    if "excel" in base_name or "vendite" in base_name or "dataset" in base_name:
        candidates.append(ASSETS_DIR / "Dataset_Test_BI_Vendite_AI_Agent.xlsx")
        candidates.append(ASSETS_DIR / "dataset_vendite.xlsx")
    elif "pdf" in base_name or "tesla" in base_name:
        candidates.append(ASSETS_DIR / "Tesla_Owner_Manual.pdf")
        candidates.append(ASSETS_DIR / "manuale_tesla.pdf")

    allowed_bases = [REPO_ROOT.resolve(), SCRIPT_DIR.resolve(), ASSETS_DIR.resolve()]
    for candidate in candidates:
        try:
            cand_res = candidate.resolve(strict=True)
            if cand_res.is_file() and any(
                cand_res.is_relative_to(b) for b in allowed_bases
            ):
                return cand_res
        except Exception:
            continue
    return None


IGNORED_SESSION_FILE_NAMES = frozenset(
    {
        "_sandbox_last_run.py",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "tsconfig.json",
        ".gitignore",
        ".env",
        "license",
        "licence",
        "contributing.md",
        "governance.md",
        "readme.md",
        "index.d.ts",
        "index.js",
    }
)

IGNORED_SESSION_DIR_PARTS = frozenset(
    {
        "node_modules",
        "__pycache__",
        ".cache",
        ".npm",
        ".venv",
        ".git",
        ".tmp",
        "tool_results",
        "docs",
    }
)


def is_user_deliverable_session_file(rel_to_session: str, p: Path) -> bool:
    """
    Determines if a file in the session sandbox is a genuine user deliverable
    (matching chat-ui's workspace file list), rather than an internal tool offload,
    unpacked document pages, package boilerplate, or sandbox dependency artifact.
    """
    rel = rel_to_session.replace("\\", "/").strip("/")
    parts = rel.split("/")

    # Strictly include only files under workspace/ (like chat-ui)
    if not rel.startswith("workspace/"):
        return False

    # Exclude any hidden files/folders or dependency caches
    for part in parts:
        if part.startswith(".") or part in IGNORED_SESSION_DIR_PARTS:
            return False

    # Exclude generic library/package/internal execution files
    file_name_lower = p.name.lower()
    if file_name_lower in IGNORED_SESSION_FILE_NAMES:
        return False

    # Exclude TypeScript declaration files
    if file_name_lower.endswith(".d.ts"):
        return False

    return True


def collect_generated_files(
    session_id: str,
    case_id: str,
    outputs_dir: Optional[Path] = None,
    initial_files: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Scans the session directory for user deliverable files generated during the test run
    (strictly under workspace/, matching chat-ui's end-of-chat workspace deliverables).
    """
    if not session_id or not SAFE_ID_RE.match(session_id):
        return []

    try:
        s_root = session_root(session_id).resolve()
        if not s_root.exists():
            return []
    except Exception:
        return []

    initial = initial_files or set()
    found_files: List[Dict[str, Any]] = []

    # Only scan workspace subdirectory (strictly matching chat-ui user deliverables)
    sub_dir = s_root / "workspace"
    if sub_dir.exists() and sub_dir.is_dir():
        for p in sub_dir.rglob("*"):
            if not p.is_file():
                continue

            try:
                rel_to_session = str(p.relative_to(s_root)).replace("\\", "/")
            except Exception:
                continue

            if rel_to_session in initial:
                continue

            if not is_user_deliverable_session_file(rel_to_session, p):
                continue

            try:
                suffix = p.suffix.lower()
                is_doc = suffix in [
                    ".docx",
                    ".xlsx",
                    ".pdf",
                    ".csv",
                    ".json",
                    ".txt",
                    ".md",
                    ".html",
                    ".xml",
                ]
                is_image = suffix in [".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"]
                is_code = suffix in [".py", ".js", ".ts", ".sh", ".sql"]

                if is_doc:
                    category = "Documento"
                elif is_image:
                    category = "Immagine / Grafico"
                elif is_code:
                    category = "Script"
                else:
                    category = "File Dati"

                session_rel_path = f"data/sessions/{session_id}/{rel_to_session}"

                found_files.append(
                    {
                        "name": p.name,
                        "suffix": suffix,
                        "category": category,
                        "is_image": is_image,
                        "is_document": is_doc,
                        "size_bytes": p.stat().st_size,
                        "relative_to_outputs": session_rel_path,
                        "session_path": session_rel_path,
                        "abs_path": str(p.resolve()),
                        "file_url": session_rel_path,
                    }
                )
            except Exception as e:
                logger.warning("Could not inspect generated file %s: %s", p, e)

    return found_files


def format_generated_files_section(
    files: List[Dict[str, Any]],
    outputs_dir: Optional[Path] = None,
    session_id: Optional[str] = None,
) -> List[str]:
    """Formats generated files into a markdown table with downloadable file links to session workspace."""
    lines: List[str] = []
    if not files and not session_id:
        return lines

    lines.append("### 📁 Documenti & File nel Workspace di Sessione")
    lines.append("")
    if session_id:
        lines.append(
            f"> 📂 **Cartella Workspace (Sandbox):** `data/sessions/{session_id}/workspace`"
        )
        lines.append("")

    if files:
        lines.append("| Nome File | Categoria | Dimensione | Download Deliverable |")
        lines.append("|---|---|---|---|")
        for f in files:
            size_kb = f["size_bytes"] / 1024
            size_str = f"{size_kb:.1f} KB" if size_kb >= 1 else f"{f['size_bytes']} B"
            rel_link = f.get("session_path", f["name"])
            link_str = f"[{f['name']}]({rel_link})"
            lines.append(
                f"| **{f['name']}** | {f['category']} | {size_str} | {link_str} |"
            )
        lines.append("")

    return lines


def format_timeline_section(timeline_events: List[Dict[str, Any]]) -> List[str]:
    """
    Formats the chronological step-by-step interleaved timeline of reasoning,
    tool calls (with parameters and execution results), and responses.
    """
    lines: List[str] = []
    lines.append("### ⏱️ Flusso di Esecuzione Cronologico (Timeline)")
    lines.append("")

    if not timeline_events:
        lines.append("_Nessun evento cronologico intercettato._")
        lines.append("")
        return lines

    step_idx = 1
    for ev in timeline_events:
        ev_type = ev.get("type")
        if ev_type == "reasoning":
            content = (ev.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"#### Passo {step_idx} — 🧠 Reasoning")
            lines.append("")
            for rline in content.splitlines():
                lines.append(f"> {rline}")
            lines.append("")
            step_idx += 1

        elif ev_type == "tool_call":
            tool_name = ev.get("name") or "unknown_tool"
            is_err = ev.get("error", False)
            params = ev.get("parameters") or {}
            result = ev.get("result")

            lines.append(f"#### Passo {step_idx} — 🛠️ Tool: `{tool_name}`")
            lines.append("")
            lines.append("- **Parametri inviati:**")
            try:
                formatted_params = json.dumps(params, indent=2, ensure_ascii=False)
            except Exception:
                formatted_params = str(params)
            lines.append("  ```json")
            for pline in formatted_params.splitlines():
                lines.append(f"  {pline}")
            lines.append("  ```")

            status_text = (
                "⚠️ **Completato con errore**"
                if is_err
                else "✓ **Eseguito con successo**"
            )
            lines.append(f"- **Esito:** {status_text}")

            if result is not None:
                res_str = str(result).strip()
                if res_str:
                    lines.append("- **Risultato:**")
                    if len(res_str) > 1500:
                        res_str = res_str[:1500] + "\n... [troncato per brevità]"
                    lines.append("  ```")
                    for rline in res_str.splitlines():
                        lines.append(f"  {rline}")
                    lines.append("  ```")
            lines.append("")
            step_idx += 1

    return lines


def format_score_section(res: Dict[str, Any]) -> List[str]:
    """Formats the granular 10-criteria scoring section with badges in Markdown."""
    lines: List[str] = []
    score = res.get("score")
    if score is None:
        return lines

    rating = res.get("rating", "A")
    passed = res.get("passed", True)
    summary = res.get("eval_summary", f"{score}/100")
    criteria = res.get("eval_criteria", [])

    badge_icon = (
        "🟢"
        if score >= 90
        else ("🟡" if score >= 75 else ("🟠" if score >= 50 else "🔴"))
    )

    lines.append(
        f"### 🎯 Valutazione Automatica & Punteggio: {badge_icon} **{score}/100** (Grado `{rating}`)"
    )
    lines.append("")
    lines.append(
        f"> **Esito:** {'✅ Superato' if passed else '❌ Non Superato'} · **Riepilogo:** {summary}"
    )
    lines.append("")

    if criteria:
        lines.append(
            "| # | Criterio | Categoria | Punti | Dettagli Rilevati / Attesi | Esito |"
        )
        lines.append("|---|---|---|:---:|---|:---:|")
        for idx, c in enumerate(criteria, start=1):
            status_icon = "✅ Superato" if c.get("passed") else "❌ Fallito"
            pts_str = f"**{c.get('points', 0)}** / {c.get('max_points', 0)}"
            lines.append(
                f"| {idx} | **{c.get('name')}** | `{c.get('category')}` | {pts_str} | {c.get('details')} | {status_icon} |"
            )
        lines.append("")

    return lines


def format_single_test_markdown(res: Dict[str, Any], outputs_dir: Path) -> str:
    """Formats an individual, standalone Markdown report for a single test case."""
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    score_str = (
        f" (Punteggio: {res.get('score', 0)}/100 [{res.get('rating', '')}])"
        if "score" in res
        else ""
    )
    status_str = (
        f"✅ COMPLETATO{score_str}"
        if res.get("status") == "completed"
        else f"❌ FALLITO ({res.get('error')})"
    )
    session_id = res.get("session_id", "")
    asst_name = res.get("assistant", "generic_assistant")
    lines = [
        f"# Smoke Test Report: {res['name']}",
        "",
        f"- **ID Test:** `{res['id']}`",
        f"- **Data Esecuzione:** {res.get('timestamp') or now_iso}",
        f"- **Profilo / Assistente:** `{asst_name}`",
        f"- **Stato:** {status_str}",
        f"- **Tempo di Esecuzione:** {res.get('duration_sec', 0)}s",
        f"- **Tool Chiamati:** {len(res.get('tool_calls', []))}",
    ]
    if session_id:
        try:
            s_root = session_root(session_id)
            lines.append(
                f"- **Cartella Sandbox Sessione:** [`data/sessions/{session_id}/workspace`]({s_root.resolve().as_uri()})"
            )
        except Exception:
            lines.append(f"- **Session ID:** `{session_id}`")
    lines.extend(
        [
            f"- **Prompt Inviato:**",
            f"  > {res.get('prompt', '')}",
        ]
    )
    if res.get("attachment"):
        lines.append(f"- **Allegato:** `{res['attachment']}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Granular scoring & criteria section
    score_section = format_score_section(res)
    if score_section:
        lines.extend(score_section)
        lines.append("---")
        lines.append("")

    # Generated documents and artifacts
    files = res.get("generated_files", [])
    if files or session_id:
        lines.extend(
            format_generated_files_section(files, outputs_dir, session_id=session_id)
        )
        lines.append("---")
        lines.append("")

    # Chronological execution timeline
    timeline = res.get("timeline", [])
    if timeline:
        lines.extend(format_timeline_section(timeline))
        lines.append("---")
        lines.append("")
    else:
        # Fallback
        lines.append("### 🧠 Reasoning")
        reasoning = res.get("reasoning", "").strip()
        lines.append(reasoning if reasoning else "_Nessun log di reasoning catturato._")
        lines.append("")
        lines.append("### 🛠️ Tool Calls")
        tool_calls = res.get("tool_calls", [])
        if tool_calls:
            for tc in tool_calls:
                lines.append(f"- **Tool:** `{tc.get('name')}`")
        else:
            lines.append("_Nessun tool invocato._")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Final Output
    lines.append("### 📝 Risposta Finale dell'Agente")
    lines.append("")
    output = res.get("final_output", "").strip()
    if output:
        lines.append(output)
    else:
        lines.append("_Nessun output testuale finale prodotto._")
    lines.append("")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


async def run_single_test(
    case: Dict[str, Any],
    *,
    profile_override: Optional[str] = None,
    outputs_dir: Path = DEFAULT_OUTPUTS_DIR,
    event_queue: Optional[asyncio.Queue] = None,
    session_prefix: str = "smoke",
    print_cli: bool = True,
) -> Dict[str, Any]:
    """
    Executes a single test case through AgentPipeline, intercepting reasoning,
    tool calls with parameters in chronological order, collecting generated files,
    and writing a standalone Markdown report.
    """
    raw_case_id = str(case.get("id", "unknown_test"))
    case_id = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_case_id)
    case_name = case.get("name", case_id)

    raw_assistant = profile_override or case.get("assistant", "generic_assistant")
    assistant_name = re.sub(r"[^a-zA-Z0-9_-]", "_", str(raw_assistant))

    prompt = case.get("prompt", "")
    attachment_rel = case.get("attachment")

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", session_prefix)
    session_id = f"{clean_prefix}_{case_id}_{timestamp_str}_{os.getpid()}"

    start_time = time.monotonic()

    if print_cli:
        print(f"\n=======================================================", flush=True)
        print(f"▶ [{case_id}] {case_name} (Profilo: {assistant_name})", flush=True)
        print(f"=======================================================", flush=True)

    async def emit(step: str, message: str, **kwargs):
        evt = {
            "status": "running",
            "test": case_id,
            "test_name": case_name,
            "assistant": assistant_name,
            "step": step,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        if event_queue is not None:
            await event_queue.put(evt)

    await emit("test_start", f"Inizio test: {case_name}")

    # Track initial files in session root to identify newly generated files later
    initial_files: Set[str] = set()
    try:
        s_root = ensure_session_dirs(session_id)
        for p in s_root.rglob("*"):
            if p.is_file():
                initial_files.add(str(p.relative_to(s_root)).replace("\\", "/"))
    except Exception:
        pass

    # Process attachment if provided
    attachments_meta: List[Dict[str, Any]] = []
    if attachment_rel:
        resolved_file = resolve_asset_path(attachment_rel)
        if resolved_file and resolved_file.exists():
            if print_cli:
                print(f"  📎 Allegato: {resolved_file.name}", flush=True)
            await emit(
                "attachment_loading",
                f"Caricamento allegato: {resolved_file.name}",
                file_name=resolved_file.name,
            )
            try:
                data = resolved_file.read_bytes()
                meta = save_upload(session_id, resolved_file.name, data)
                attachments_meta.append(meta)
                if meta.get("relative_path"):
                    initial_files.add(meta.get("relative_path").replace("\\", "/"))
                await emit(
                    "attachment_ready",
                    f"Allegato registrato nella sandbox: {meta.get('relative_path')}",
                    relative_path=meta.get("relative_path"),
                )
            except Exception as ex:
                if print_cli:
                    print(f"  ⚠️ Errore caricamento allegato: {ex}", flush=True)
                await emit(
                    "attachment_error",
                    f"Errore caricamento allegato: {ex}",
                    error=str(ex),
                )
        else:
            if print_cli:
                print(f"  ⚠️ Allegato non trovato: {attachment_rel}", flush=True)
            await emit(
                "attachment_missing",
                f"Allegato non trovato: {attachment_rel}",
                warning=f"Asset file {attachment_rel} could not be resolved",
            )

    reasoning_chunks: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    final_output_chunks: List[str] = []
    timeline: List[Dict[str, Any]] = []
    current_reasoning_buffer: List[str] = []
    current_tool_call: Optional[Dict[str, Any]] = None
    error_msg: Optional[str] = None

    has_started_reasoning = False
    has_started_output = False

    def flush_reasoning():
        nonlocal current_reasoning_buffer
        if current_reasoning_buffer:
            text = "".join(current_reasoning_buffer).strip()
            if text:
                timeline.append(
                    {
                        "type": "reasoning",
                        "content": text,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            current_reasoning_buffer = []

    try:
        agent_instance, profile_name = await get_agent(
            assistant_name,
            session_id=session_id,
            user_id="smoke_test",
        )
        pipeline = AgentPipeline(
            agent=agent_instance,
            session_id=session_id,
            profile_name=profile_name,
            user_id="smoke_test",
        )

        stream_gen = pipeline.run_stream(
            prompt,
            attachments=attachments_meta if attachments_meta else None,
            turn_attachments=attachments_meta if attachments_meta else None,
        )

        async for chunk in stream_gen:
            chunk_type = chunk.get("type", "")

            # Reasoning
            if chunk_type == "reasoning":
                reasoning_text = chunk.get("reasoning") or chunk.get("content") or ""
                if reasoning_text:
                    reasoning_chunks.append(reasoning_text)
                    current_reasoning_buffer.append(reasoning_text)
                    if print_cli and not has_started_reasoning:
                        print("  ⚙️  Ragionamento in corso...", flush=True)
                        has_started_reasoning = True
                    await emit(
                        "reasoning",
                        "Ragionamento in corso...",
                        content=reasoning_text,
                    )

            # Output tokens
            elif chunk_type == "token":
                flush_reasoning()
                token_text = chunk.get("content", "")
                if token_text:
                    final_output_chunks.append(token_text)
                    await emit("token", "Generazione risposta...", token=token_text)

            # Tool events
            elif chunk_type == "tool_event":
                evt_inner = chunk.get("event") or {}
                evt_type = evt_inner.get("type")
                tool_name = (
                    evt_inner.get("name")
                    or evt_inner.get("tool_name")
                    or "unknown_tool"
                )

                if evt_type == "tool_start":
                    flush_reasoning()
                    has_started_reasoning = False

                    # If text tokens arrived before this tool, they are part of the intermediate reasoning/thought process
                    if final_output_chunks:
                        pre_tool_thought = "".join(final_output_chunks).strip()
                        if pre_tool_thought:
                            reasoning_chunks.append(f"\n{pre_tool_thought}\n")
                            timeline.append(
                                {
                                    "type": "reasoning",
                                    "content": pre_tool_thought,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                            await emit(
                                "reasoning",
                                "Ragionamento",
                                content=pre_tool_thought,
                            )
                        final_output_chunks = []

                    tool_input = (
                        evt_inner.get("input")
                        if "input" in evt_inner
                        else evt_inner.get("arguments") or {}
                    )
                    current_tool_call = {
                        "type": "tool_call",
                        "name": tool_name,
                        "parameters": tool_input,
                        "id": evt_inner.get("id"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "status": "running",
                    }

                    if print_cli:
                        param_summary = ""
                        if isinstance(tool_input, dict):
                            if "relative_path" in tool_input:
                                param_summary = f" -> {tool_input['relative_path']}"
                            elif "query" in tool_input:
                                param_summary = f" -> '{str(tool_input['query'])[:60]}'"
                            elif "command" in tool_input:
                                param_summary = (
                                    f" -> '{str(tool_input['command'])[:60]}'"
                                )
                            elif "title" in tool_input:
                                param_summary = f" -> '{str(tool_input['title'])[:60]}'"
                        print(f"  🛠️  Tool: {tool_name}{param_summary}", flush=True)

                    await emit(
                        "tool_call",
                        f"Esecuzione tool: {tool_name}",
                        tool=tool_name,
                        params=tool_input,
                    )

                elif evt_type in ("tool_end", "tool_error"):
                    is_err = evt_type == "tool_error" or evt_inner.get("error", False)
                    result_raw = (
                        evt_inner.get("result")
                        if "result" in evt_inner
                        else evt_inner.get("error")
                    )
                    result_preview = str(result_raw or "")[:200]

                    if current_tool_call:
                        current_tool_call["status"] = "error" if is_err else "success"
                        current_tool_call["error"] = is_err
                        current_tool_call["result"] = result_raw
                        tool_calls.append(current_tool_call)
                        timeline.append(current_tool_call)
                        current_tool_call = None
                    else:
                        entry = {
                            "type": "tool_call",
                            "name": tool_name,
                            "parameters": {},
                            "status": "error" if is_err else "success",
                            "error": is_err,
                            "result": result_raw,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        tool_calls.append(entry)
                        timeline.append(entry)

                    if print_cli:
                        if is_err:
                            print(
                                f"     ⚠️ Tool completato con errore: {result_preview[:80]}",
                                flush=True,
                            )
                        else:
                            print(f"     ✓ Tool eseguito con successo", flush=True)

                    await emit(
                        "tool_result",
                        f"Completato tool: {tool_name}"
                        if not is_err
                        else f"Errore tool: {tool_name}",
                        tool=tool_name,
                        error=is_err,
                        preview=result_preview,
                        result=result_raw,
                    )

            # Errors
            elif chunk_type in ("error", "llm_error", "context_length_error"):
                error_msg = str(
                    chunk.get("content") or chunk.get("error") or "Unknown error"
                )
                if print_cli:
                    print(f"  ❌ Errore agente: {error_msg}", flush=True)
                await emit("test_error", f"Errore: {error_msg}", error=error_msg)

    except Exception as ex:
        logger.exception("Error executing test case %s", case_id)
        error_msg = str(ex)
        if print_cli:
            print(f"  ❌ Eccezione durante l'esecuzione: {ex}", flush=True)
        await emit("test_error", f"Eccezione durante il test: {ex}", error=error_msg)

    # Flush any remaining reasoning or unclosed tool calls
    flush_reasoning()
    if current_tool_call:
        tool_calls.append(current_tool_call)
        timeline.append(current_tool_call)
        current_tool_call = None

    elapsed = round(time.monotonic() - start_time, 2)
    full_reasoning = "".join(reasoning_chunks).strip()
    full_output = "".join(final_output_chunks).strip()
    status = "failed" if error_msg else "completed"

    # Scan and collect generated files from session sandbox
    generated_files = collect_generated_files(
        session_id=session_id,
        case_id=case_id,
        outputs_dir=outputs_dir,
        initial_files=initial_files,
    )

    test_result: Dict[str, Any] = {
        "id": case_id,
        "name": case_name,
        "assistant": assistant_name,
        "session_id": session_id,
        "prompt": prompt,
        "attachment": attachment_rel,
        "duration_sec": elapsed,
        "reasoning": full_reasoning,
        "tool_calls": tool_calls,
        "timeline": timeline,
        "generated_files": generated_files,
        "final_output": full_output,
        "status": status,
        "error": error_msg,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Evaluate static assertions and score (0-100)
    try:
        s_root_p = ensure_session_dirs(session_id)
        eval_res = evaluate_test(
            test_id=case_id,
            test_result=test_result,
            session_id=session_id,
            session_dir=s_root_p if s_root_p.exists() else None,
        )
        test_result["score"] = eval_res.score
        test_result["max_score"] = eval_res.max_score
        test_result["rating"] = eval_res.rating
        test_result["passed"] = eval_res.passed
        test_result["eval_summary"] = eval_res.summary
        test_result["eval_criteria"] = [c.to_dict() for c in eval_res.criteria]
    except Exception as eval_err:
        logger.warning("Error evaluating test %s: %s", case_id, eval_err)
        test_result["score"] = 0
        test_result["max_score"] = 100
        test_result["rating"] = "F"
        test_result["passed"] = False
        test_result["eval_summary"] = f"Evaluation error: {eval_err}"
        test_result["eval_criteria"] = []

    if print_cli:
        score_badge = f"🎯 Punteggio: {test_result.get('score', 0)}/100 [{test_result.get('rating', 'F')}] ({test_result.get('eval_summary', '')})"
        if status == "completed" and test_result.get("passed", True):
            print(
                f"  ✅ COMPLETATO in {elapsed}s (Tool: {len(tool_calls)}) · {score_badge}\n",
                flush=True,
            )
        else:
            print(
                f"  ❌ {status.upper()} in {elapsed}s (Tool: {len(tool_calls)}) · {score_badge}\n",
                flush=True,
            )

    # Save standalone Markdown report for this test immediately (fixed name per test)
    outputs_dir_res = Path(outputs_dir).resolve()
    outputs_dir_res.mkdir(parents=True, exist_ok=True)
    raw_case_id = str(case.get("id", "unknown"))
    safe_case_id = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_case_id) or "unknown"
    single_report_filename = f"report_{safe_case_id}.md"
    single_report_path = (outputs_dir_res / single_report_filename).resolve()
    single_report_content = format_single_test_markdown(test_result, outputs_dir_res)

    if single_report_path.is_relative_to(outputs_dir_res):
        try:
            with open(single_report_path, "w", encoding="utf-8") as srf:
                srf.write(single_report_content)
            test_result["single_report_path"] = str(single_report_path)
            test_result["single_report_filename"] = single_report_filename
            if print_cli:
                print(
                    f"  📄 Report salvato: outputs/{single_report_filename}", flush=True
                )
        except Exception as ex:
            logger.warning(
                "Could not write single test report %s: %s", single_report_path, ex
            )

    await emit(
        "test_complete",
        f"Test completato in {elapsed}s · Punteggio: {test_result.get('score', 0)}/100 [{test_result.get('rating', '')}]"
        if status == "completed"
        else f"Test fallito in {elapsed}s: {error_msg}",
        duration_sec=elapsed,
        status=status,
        score=test_result.get("score", 0),
        max_score=test_result.get("max_score", 100),
        rating=test_result.get("rating", "F"),
        passed=test_result.get("passed", False),
        eval_summary=test_result.get("eval_summary", ""),
        eval_criteria=test_result.get("eval_criteria", []),
        assistant=assistant_name,
        tool_count=len(tool_calls),
        final_output=full_output,
        reasoning=full_reasoning,
        tool_calls=tool_calls,
        timeline=timeline,
        generated_files=generated_files,
        single_report_filename=single_report_filename,
    )

    return test_result


def format_markdown_report(
    results: List[Dict[str, Any]],
    execution_mode: str = "sequential",
    outputs_dir: Optional[Path] = None,
) -> str:
    """Formats the test results into the complete multi-test suite Markdown report."""
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = [
        f"# Smoke Test Execution Report",
        f"- **Data:** {now_iso}",
        f"- **Modalità:** {execution_mode.capitalize()}",
        f"- **Test Totali:** {len(results)}",
        f"- **Completati con successo:** {sum(1 for r in results if r.get('status') == 'completed')}",
        f"- **Falliti:** {sum(1 for r in results if r.get('status') == 'failed')}",
        "",
        "---",
        "",
    ]

    for res in results:
        asst = res.get("assistant", "generic_assistant")
        lines.append(f"## Test {res['id']}: {res['name']}")
        lines.append(f"**Profilo / Assistente:** `{asst}`")
        lines.append(f"**Tempo di esecuzione:** {res['duration_sec']}s")
        if res.get("attachment"):
            lines.append(f"**Allegato:** `{res['attachment']}`")
        if res.get("status") == "failed":
            lines.append(f"**Stato:** ❌ FALLITO ({res.get('error')})")
        lines.append("")

        # Granular scoring & criteria section
        score_section = format_score_section(res)
        if score_section:
            lines.extend(score_section)
            lines.append("")

        # Generated files section if present
        files = res.get("generated_files", [])
        session_id = res.get("session_id", "")
        if files or session_id:
            lines.extend(
                format_generated_files_section(
                    files, outputs_dir, session_id=session_id
                )
            )
            lines.append("")

        # Chronological timeline if available
        timeline = res.get("timeline", [])
        if timeline:
            lines.extend(format_timeline_section(timeline))
        else:
            # Fallback for compatibility
            lines.append("### 🧠 Reasoning")
            reasoning = res.get("reasoning", "").strip()
            if reasoning:
                lines.append(reasoning)
            else:
                lines.append(
                    "_Nessun log di reasoning separato catturato dal provider o non applicabile._"
                )
            lines.append("")

            lines.append("### 🛠️ Tool Calls")
            tool_calls = res.get("tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    lines.append(f"- **Tool:** `{tc.get('name')}`")
                    lines.append("- **Parametri:**")
                    params = tc.get("parameters") or {}
                    try:
                        formatted_params = json.dumps(
                            params, indent=2, ensure_ascii=False
                        )
                    except Exception:
                        formatted_params = str(params)
                    lines.append("  ```json")
                    for pline in formatted_params.splitlines():
                        lines.append(f"  {pline}")
                    lines.append("  ```")
            else:
                lines.append("_Nessun tool MCP/Sandbox invocato durante questo test._")
            lines.append("")

        lines.append("### 📝 Output Finale")
        output = res.get("final_output", "").strip()
        if output:
            lines.append(output)
        else:
            lines.append("_Nessun output testuale finale prodotto._")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _safe_report_test_id(test_id: str) -> str:
    """
    Validate test_id before using it in a filename.
    Allows only alphanumerics, underscore, and dash.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", test_id):
        raise ValueError("Invalid test_id for report filename")
    if test_id in {".", ".."}:
        raise ValueError("Invalid test_id for report filename")
    return test_id


async def run_smoke_tests(
    config_path: Path = DEFAULT_CONFIG_PATH,
    outputs_dir: Path = DEFAULT_OUTPUTS_DIR,
    test_id: Optional[str] = None,
    profile: Optional[str] = None,
    event_queue: Optional[asyncio.Queue] = None,
    is_cli: bool = False,
) -> tuple[List[Dict[str, Any]], Path, str]:
    """
    Main suite executor. Runs test cases sequentially,
    generates standalone and suite Markdown reports incrementally, and writes to disk in real-time.
    """
    mute_internal_loggers()
    await ensure_db_ready()

    set_event_loop(asyncio.get_running_loop())

    config_path_res = Path(config_path).resolve()
    if not config_path_res.exists():
        raise FileNotFoundError(f"Config file not found at: {config_path_res}")

    with open(config_path_res, "r", encoding="utf-8") as f:
        cases: List[Dict[str, Any]] = json.load(f)

    if test_id:
        if not SAFE_ID_RE.match(test_id):
            raise ValueError(f"Invalid test_id format: {test_id}")
        cases = [c for c in cases if c.get("id") == test_id]
        if not cases:
            raise ValueError(f"No test case found with id: {test_id}")

    if profile and not SAFE_ID_RE.match(profile):
        raise ValueError(f"Invalid profile format: {profile}")

    outputs_dir_res = Path(outputs_dir).resolve()
    outputs_dir_res.mkdir(parents=True, exist_ok=True)
    if test_id:
        safe_test_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(test_id))
        report_filename = f"report_{safe_test_id}.md"
    else:
        report_filename = "report_suite_summary.md"
    report_path = (outputs_dir_res / report_filename).resolve()

    if not report_path.is_relative_to(outputs_dir_res):
        raise ValueError("Report path traversal blocked")

    target_profile_label = profile or "Generic Assistant (da config)"
    if event_queue is not None:
        await event_queue.put(
            {
                "status": "running",
                "step": "suite_start",
                "message": f"Avvio suite di test (Sequenziale) - {len(cases)} test da eseguire (Profilo: {target_profile_label})",
                "test_count": len(cases),
                "profile": target_profile_label,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    results: List[Dict[str, Any]] = []

    def flush_suite_report():
        if results and report_path.is_relative_to(outputs_dir_res):
            content = format_markdown_report(
                results,
                execution_mode="sequential",
                outputs_dir=outputs_dir_res,
            )
            try:
                with open(report_path, "w", encoding="utf-8") as rf:
                    rf.write(content)
                return content
            except Exception as ex:
                logger.warning("Could not write suite report: %s", ex)
        return ""

    try:
        for idx, case in enumerate(cases, 1):
            if is_cli:
                print(f"[{idx}/{len(cases)}]", end=" ", flush=True)
            res = await run_single_test(
                case,
                profile_override=profile,
                outputs_dir=outputs_dir_res,
                event_queue=event_queue,
                session_prefix="smoke_seq",
                print_cli=is_cli,
            )
            results.append(res)
            # Incrementally update suite report on disk immediately after each test finishes
            flush_suite_report()
            if is_cli:
                print(
                    f"  💾 Report suite aggiornato: outputs/{report_filename}\n",
                    flush=True,
                )

    finally:
        report_content = flush_suite_report()

    if event_queue is not None:
        await event_queue.put(
            {
                "status": "completed",
                "step": "suite_complete",
                "message": f"Tutti i test completati. Report generato in {report_filename}.",
                "report_filename": report_filename,
                "report_path": str(report_path),
                "report_content": report_content,
                "profile": target_profile_label,
                "results_summary": [
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "assistant": r.get("assistant"),
                        "duration_sec": r["duration_sec"],
                        "status": r["status"],
                        "tool_calls_count": len(r.get("tool_calls", [])),
                        "generated_files_count": len(r.get("generated_files", [])),
                        "single_report_filename": r.get("single_report_filename"),
                    }
                    for r in results
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    return results, report_path, report_content


async def run_smoke_tests_stream(
    test_id: Optional[str] = None,
    profile: Optional[str] = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    outputs_dir: Path = DEFAULT_OUTPUTS_DIR,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Async generator yielding real-time SSE event dicts while executing smoke tests sequentially.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def _worker():
        try:
            await run_smoke_tests(
                config_path=config_path,
                outputs_dir=outputs_dir,
                test_id=test_id,
                profile=profile,
                event_queue=queue,
                is_cli=False,
            )
        except Exception as ex:
            logger.exception("Suite worker failed: %s", ex)
            await queue.put(
                {
                    "status": "failed",
                    "step": "suite_error",
                    "message": f"Errore esecuzione suite: {str(ex)}",
                    "error": str(ex),
                }
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(_worker())

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item

    await task


def main():
    parser = argparse.ArgumentParser(description="AION Agent Smoke Tests Runner")
    parser.add_argument(
        "--test",
        "-t",
        type=str,
        default=None,
        help="Run only a specific test ID (e.g. test_1_excel)",
    )
    parser.add_argument(
        "--profile",
        "-p",
        type=str,
        default=None,
        help="Target agent profile slug to run tests against (e.g. generic_assistant, aion_std)",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to test_config.json",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=str(DEFAULT_OUTPUTS_DIR),
        help="Directory to write output Markdown reports",
    )

    args = parser.parse_args()

    mute_internal_loggers()

    target_profile_display = args.profile or "Generic Assistant (default)"

    print("\n" + "=" * 60, flush=True)
    print(" 🚀 AION AGENT SMOKE TESTS (CLI)", flush=True)
    print(f" 🤖 Profilo target: {target_profile_display}", flush=True)
    print(" ⚙️  Modalità: SEQUENZIALE", flush=True)
    print("=" * 60, flush=True)

    cfg_path = Path(args.config)
    out_dir = Path(args.output_dir)

    total_start = time.monotonic()
    results = []
    report_path = out_dir / "report_smoke_test_aborted.md"

    try:
        results, report_path, _ = asyncio.run(
            run_smoke_tests(
                config_path=cfg_path,
                outputs_dir=out_dir,
                test_id=args.test,
                profile=args.profile,
                is_cli=True,
            )
        )
    except KeyboardInterrupt:
        print(
            "\n\n⚠️  Esecuzione interrotta dall'utente (Ctrl+C). Salvataggio report parziale completato.",
            flush=True,
        )
        return

    total_elapsed = round(time.monotonic() - total_start, 2)
    passed_count = sum(1 for r in results if r.get("status") == "completed")

    print("\n" + "=" * 60, flush=True)
    print(" 📊 RIEPILOGO RISULTATI", flush=True)
    print("=" * 60, flush=True)
    for r in results:
        status_sym = "✅" if r.get("status") == "completed" else "❌"
        status_text = (
            "OK" if r.get("status") == "completed" else f"FALLITO ({r.get('error')})"
        )
        asst_label = f"[{r.get('assistant', 'generic_assistant')}]"
        print(
            f" {status_sym} [{r['id']}] {r['name']:<32} {asst_label} {r['duration_sec']}s  (Tools: {len(r.get('tool_calls', []))}) -> {status_text}",
            flush=True,
        )
    print("-" * 60, flush=True)
    print(
        f" 🎉 Esito finale: {passed_count}/{len(results)} superati in {total_elapsed}s",
        flush=True,
    )
    for r in results:
        rep_name = r.get("single_report_filename") or f"report_{r['id']}.md"
        print(f" 📄 Report Markdown: outputs/{rep_name}", flush=True)
    print("=" * 60 + "\n", flush=True)


if __name__ == "__main__":
    main()
