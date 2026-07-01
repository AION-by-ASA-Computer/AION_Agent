import asyncio
import base64
import json
import logging
import re
import mimetypes
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

try:
    from opik import track
except ImportError:

    def track(*_args, **_kwargs):
        def decorator(fn):
            return fn

        return decorator


import requests
from haystack.dataclasses import ChatMessage, FileContent, ImageContent

from .haystack_chat import chat_message_text
from .main import set_event_loop
from .runtime.tool_events import tool_event_bus
from .runtime.redis_client import (
    redis_clear_stream_active,
    redis_consume_force_compact,
    redis_consume_stream_cancel,
    redis_set_stream_active,
)
from .api.history import history_manager
from .memory.ltm_orchestrator import ltm_orchestrator
from .memory import stm_consolidator
from .memory.context_compressor import (
    CompactionTranscriptRow,
    build_transcript_from_rows,
    count_tokens,
    estimate_agent_overhead_tokens,
    estimate_full_prompt_tokens,
    format_compaction_block,
    get_default_compressor,
    is_context_length_error,
    log_context_budget,
    model_context_window,
    reserve_output_tokens,
    truncate_messages_to_prompt_budget,
)
from .runtime.hooks import HookContext, hook_registry
from .runtime.reasoning_effort import generation_kwargs_for_agent
from .runtime.artifact_parser import (
    XMLArtifactStreamParser,
    MarkdownArtifactStreamParser,
    NoOpArtifactParser,
    PlanTagInterceptorParser,
    ArtifactEvent,
)
from .runtime.artifact_manager import ArtifactManager
from .runtime.stream_sync import StreamSync
from .data.message_roles import normalize_message_role

logger = logging.getLogger("aion.pipeline")
logger.setLevel(logging.INFO)

# Haystack Agent su errore serializza gli input del chat_generator: niente closure annidate.
from .runtime.context import clear_context, get_context, set_context
from .runtime.turn_compaction import (
    clear_turn_runtime,
    maybe_compact_after_reasoning,
    set_turn_runtime,
)


def _agent_debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    run_id: str = "turn",
) -> None:
    from src.runtime.turn_diagnostics import agent_debug_log

    agent_debug_log(hypothesis_id, location, message, data, run_id=run_id)


def _chunk_counters(chunk_type: str, event_type: str = "") -> tuple[int, int]:
    """Return (control_events_inc, output_events_inc) for stream budgeting."""
    if chunk_type == "tool_event":
        return (1, 0)
    if chunk_type in (
        "token",
        "reasoning",
        "artifact_start",
        "artifact_content",
        "artifact_end",
    ):
        return (0, 1)
    if chunk_type == "stream_end":
        return (1, 0)
    if chunk_type == "error":
        return (1, 0)
    if event_type == "request_sync":
        return (1, 0)
    return (0, 0)


_PLAN_TAG_IN_PAYLOAD_RE = re.compile(r"<plan\b", re.IGNORECASE)


def _is_plan_artifact_payload(
    artifact_id: str, artifact_type: str, content: str = ""
) -> bool:
    a_type = (artifact_type or "").strip().lower()
    if a_type == "plan":
        return True
    aid = (artifact_id or "").strip().lower()
    if aid.startswith("execution_plan_"):
        return True
    return bool(_PLAN_TAG_IN_PAYLOAD_RE.search(content or ""))


def _resolve_turn_plan_id(
    plan_controller: Any,
    artifact_id: Optional[str] = None,
) -> str:
    """Stable plan_id for the current plan-mode turn (Fase A)."""
    if plan_controller is not None and getattr(plan_controller, "plan_id", None):
        return str(plan_controller.plan_id).strip()
    return (artifact_id or "execution_plan").strip()


def _plan_turn_metadata_json(
    plan_id: Optional[str],
    plan_execution_task_id: Optional[str],
) -> Optional[str]:
    pid = (plan_id or "").strip()
    tid = (plan_execution_task_id or "").strip()
    if not pid and not tid:
        return None
    return json.dumps(
        {"plan_id": pid or None, "plan_task_id": tid or None},
        ensure_ascii=False,
    )


def _plan_artifact_sse_end(pe, *, plan_id: Optional[str] = None) -> Dict[str, Any]:
    """SSE artifact_end for plans: DB is SSOT, no workspace file."""
    pid = (plan_id or pe.artifact_id or "execution_plan").strip()
    return {
        "identifier": pid,
        "type": pe.artifact_type or "plan",
        "title": pe.artifact_title,
        "path": "",
        "storage_key": f"orchestration://{pid}",
        "version": 0,
        "saved": False,
    }


async def _setup_plan_artifact_chunk(
    *,
    session_id: str,
    user_id: str,
    artifact_id: str,
    markdown_content: str,
) -> Optional[Dict[str, Any]]:
    """Register a plan artifact for all clients and return the pending-plan SSE chunk."""
    body = (markdown_content or "").strip()
    pid = (artifact_id or "").strip()
    if not pid or not body:
        return None
    try:
        from .runtime.orchestration_tools import setup_execution_plan_from_markdown
        from .a2a.plan_markdown import markdown_to_plan, plan_to_todos
        from .a2a.protocol import ExecutionPlan

        registered = await setup_execution_plan_from_markdown(
            body,
            plan_id=pid,
            session_id=session_id,
            user_id=user_id,
        )
        if not registered:
            logger.warning(
                "Plan artifact not registered in DB for %s (session %s) — skipping pending SSE",
                pid,
                session_id,
            )
            return None
        try:
            parsed = markdown_to_plan(body)
        except Exception:
            parsed = ExecutionPlan.from_goal_and_tasks("Execution plan", [])
        return {
            "type": "orchestration_plan_pending",
            "plan_id": pid,
            "plan": json.loads(parsed.model_dump_json()),
            "plan_markdown": body,
            "todos": plan_to_todos(parsed),
            "annotations": {},
            "revision": 1,
            "goal": parsed.goal,
            "force_sidebar_refresh": True,
        }
    except Exception as exc:
        logger.warning("Plan artifact setup failed for %s: %s", pid, exc)
        return None


def _emit_agent_stream_event(ctx: dict, event: dict, *, from_async: bool) -> None:
    """Enqueue SSE events from sync (worker thread) or async (run_async) agent paths."""
    queue = ctx["queue"]
    if from_async:
        queue.put_nowait(event)
    else:
        ctx["loop"].call_soon_threadsafe(queue.put_nowait, event)


def _handle_haystack_stream_chunk(chunk: Any, *, from_async: bool) -> None:
    ctx = get_context()
    if not ctx:
        return

    stop_event = ctx.get("stop_event")
    if stop_event and stop_event.is_set():
        _agent_debug_log(
            "H2",
            "haystack_agent_streaming_callback",
            "token_dropped_stop_event_set",
            {"session_id": str(ctx.get("session_id", ""))[:12]},
        )
        return

    meta = getattr(chunk, "meta", None) or {}
    fr = getattr(chunk, "finish_reason", None) or meta.get("finish_reason")

    # Resolve reasoning/thinking tokens from chunk.reasoning (Anthropic, Google) or meta (OpenAI)
    reasoning = None
    chunk_reasoning = getattr(chunk, "reasoning", None)
    if chunk_reasoning is not None:
        if isinstance(chunk_reasoning, str):
            reasoning = chunk_reasoning
        elif hasattr(chunk_reasoning, "reasoning_text"):
            reasoning = chunk_reasoning.reasoning_text
    if not reasoning:
        reasoning = meta.get("reasoning") or meta.get("reasoning_content")

    if fr:
        logger.debug("Stream turn finished (reason: %s)", fr)
        _step = 0
        try:
            from src.runtime.turn_compaction import bump_llm_step

            _step = bump_llm_step()
        except Exception:
            pass
        _agent_debug_log(
            "H3",
            "haystack_agent_streaming_callback:stream_end",
            "llm_completion_finished",
            {
                "session_id": str(ctx.get("session_id", ""))[:12],
                "llm_step": _step,
                "finish_reason": str(fr),
                "content_len": len(str(chunk.content or "")),
                "reasoning_meta_len": len(str(reasoning or "")),
            },
        )
        _emit_agent_stream_event(ctx, {"type": "stream_end"}, from_async=from_async)

    if fr == "length":
        logger.warning("Agent response truncated by model (finish_reason=length).")

    if reasoning:
        sid = ctx.get("session_id")
        if sid:
            StreamSync.mark_busy(sid)
        try:
            maybe_compact_after_reasoning(
                reasoning if isinstance(reasoning, str) else str(reasoning)
            )
        except Exception:
            pass
        _emit_agent_stream_event(
            ctx, {"type": "reasoning", "reasoning": reasoning}, from_async=from_async
        )

    if chunk.content is not None and chunk.content != "":
        sid = ctx.get("session_id")
        if sid:
            StreamSync.mark_busy(sid)
        _emit_agent_stream_event(
            ctx, {"type": "token", "content": chunk.content}, from_async=from_async
        )


async def haystack_agent_streaming_callback_async(chunk: Any) -> None:
    """Async callback required by Haystack Agent.run_async."""
    _handle_haystack_stream_chunk(chunk, from_async=True)


def haystack_agent_streaming_callback(chunk: Any) -> None:
    """Sync callback for legacy Agent.run in a worker thread."""
    _handle_haystack_stream_chunk(chunk, from_async=False)


def _find_input_end_index(
    messages: List[ChatMessage], turn_messages: List[ChatMessage]
) -> int:
    if not messages:
        return -1
    target = messages[-1]
    target_text = chat_message_text(target)
    target_role = (
        target.role.value if hasattr(target.role, "value") else str(target.role)
    )

    # Cerca prima per identità di oggetto (più veloce e sicuro)
    for i in range(len(turn_messages) - 1, -1, -1):
        if turn_messages[i] is target:
            return i

    # Fallback: cerca per contenuto e ruolo partendo dalla fine
    for i in range(len(turn_messages) - 1, -1, -1):
        m = turn_messages[i]
        m_role = m.role.value if hasattr(m.role, "value") else str(m.role)
        if m_role == target_role and chat_message_text(m) == target_text:
            return i

    return -1


def _chat_multimodal_attachments_enabled() -> bool:
    """When true, session images (and optionally PDFs) are embedded as native Haystack ChatMessage parts."""
    return os.getenv("AION_CHAT_MULTIMODAL_ATTACHMENTS", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _chat_multimodal_pdf_embed_enabled() -> bool:
    """Haystack FileContent → OpenAI 'file' parts; many OpenAI-compat servers (e.g. vLLM) return 501."""
    return os.getenv("AION_CHAT_MULTIMODAL_PDF", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _chat_multimodal_pdf_compat_enabled() -> bool:
    """Rasterize PDF pages to PNG ImageContent (vision-only stacks that reject native file parts)."""
    return os.getenv(
        "AION_CHAT_MULTIMODAL_PDF_COMPATIBILITY_MODE", "0"
    ).strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _pdf_pages_as_image_contents(
    path: Path,
    relative_path: str,
    *,
    max_pages: int,
    max_side_px: int,
) -> List[ImageContent]:
    """Render PDF pages as PNG-backed ImageContent (PyMuPDF). Empty list on failure."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning(
            "PyMuPDF (fitz) missing: cannot use PDF compatibility raster mode"
        )
        return []

    out: List[ImageContent] = []
    doc = None
    try:
        doc = fitz.open(path)
        n_pages = min(int(doc.page_count), max(1, max_pages))
        total = int(doc.page_count)
        for i in range(n_pages):
            page = doc.load_page(i)
            rect = page.rect
            mw, mh = float(rect.width), float(rect.height)
            if mw <= 0 or mh <= 0:
                continue
            long_side = max(mw, mh)
            # Cap raster size; allow up to 2x zoom on small pages for readability.
            scale = min(2.0, float(max_side_px) / long_side) if long_side > 0 else 1.0
            mat = fitz.Matrix(scale, scale)
            try:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                png_bytes = pix.tobytes("png")
            except Exception as ex:
                logger.warning(
                    "PDF raster failed %s page=%s: %s", relative_path, i + 1, ex
                )
                continue
            b64 = base64.b64encode(png_bytes).decode("ascii")
            out.append(
                ImageContent(
                    base64_image=b64,
                    mime_type="image/png",
                    meta={
                        "relative_path": relative_path,
                        "pdf_page": i + 1,
                        "pdf_pages_total": total,
                        "source": "session_attachment_pdf_compat",
                    },
                    validation=True,
                )
            )
    except Exception as ex:
        logger.warning("PDF open/raster failed %s: %s", relative_path, ex)
        return out
    finally:
        if doc is not None:
            doc.close()
    return out


def _attachment_mime(path: Path, att: Dict[str, Any]) -> str:
    raw = (att.get("mime") or "").strip()
    if raw:
        return raw.split(";")[0].strip().lower()
    guessed, _ = mimetypes.guess_type(path.name)
    return (guessed or "application/octet-stream").lower()


def _build_user_turn_chat_message(
    session_id: str,
    user_input: str,
    attachments: Optional[List[Dict[str, Any]]],
    attach_block: str,
) -> ChatMessage:
    """
    Build the user ChatMessage for this turn. Default: plain text (attach_block + user_input).
    With AION_CHAT_MULTIMODAL_ATTACHMENTS=1, raster images are attached as ImageContent (vision).
    PDFs: optional ``AION_CHAT_MULTIMODAL_PDF_COMPATIBILITY_MODE=1`` rasterizes pages to PNG images
    (PyMuPDF) for stacks that reject native ``file`` parts; or ``AION_CHAT_MULTIMODAL_PDF=1`` for
    Haystack FileContent when the LLM server supports it. Otherwise PDFs stay in the text list + OCR.
    """
    full_text = attach_block + user_input
    if not attachments or not _chat_multimodal_attachments_enabled():
        return ChatMessage.from_user(full_text)

    from src.session_workspace import safe_resolve

    max_bytes = int(os.getenv("AION_CHAT_MULTIMODAL_MAX_BYTES", str(25 * 1024 * 1024)))
    max_parts = max(1, int(os.getenv("AION_CHAT_MULTIMODAL_MAX_FILES", "8")))

    parts: List[Union[str, ImageContent, FileContent]] = []
    n_embedded = 0
    for a in attachments:
        if n_embedded >= max_parts:
            break
        rel = (a.get("relative_path") or "").strip()
        if not rel:
            continue
        try:
            path = safe_resolve(session_id, rel, must_exist=True)
        except Exception as ex:
            logger.warning("Multimodal skip (resolve %s): %s", rel, ex)
            continue
        try:
            size_b = path.stat().st_size
        except OSError as ex:
            logger.warning("Multimodal skip (stat %s): %s", rel, ex)
            continue
        if size_b > max_bytes:
            logger.info(
                "Multimodal skip (size %s bytes > limit %s): %s",
                size_b,
                max_bytes,
                rel,
            )
            continue

        mime = _attachment_mime(path, a)
        ext = path.suffix.lower()

        if mime.startswith("image/"):
            try:
                parts.append(
                    ImageContent.from_file_path(
                        path,
                        meta={"relative_path": rel, "source": "session_attachment"},
                    )
                )
                n_embedded += 1
            except Exception as ex:
                logger.warning("Multimodal skip (image %s): %s", rel, ex)
        elif mime == "application/pdf" or ext == ".pdf":
            if _chat_multimodal_pdf_compat_enabled():
                max_pages_cfg = max(
                    1, int(os.getenv("AION_CHAT_MULTIMODAL_PDF_MAX_PAGES", "5"))
                )
                max_side = max(
                    256,
                    int(os.getenv("AION_CHAT_MULTIMODAL_PDF_RASTER_MAX_SIDE", "2048")),
                )
                rendered = _pdf_pages_as_image_contents(
                    path, rel, max_pages=max_pages_cfg, max_side_px=max_side
                )
                if not rendered:
                    logger.info("PDF compatibility mode produced no images for %s", rel)
                for img in rendered:
                    if n_embedded >= max_parts:
                        break
                    parts.append(img)
                    n_embedded += 1
            elif _chat_multimodal_pdf_embed_enabled():
                try:
                    fname = (a.get("original_name") or path.name) or "document.pdf"
                    parts.append(
                        FileContent.from_file_path(
                            path,
                            filename=str(fname)[:512],
                            extra={
                                "relative_path": rel,
                                "source": "session_attachment",
                            },
                        )
                    )
                    n_embedded += 1
                except Exception as ex:
                    logger.warning("Multimodal skip (pdf file part %s): %s", rel, ex)
            else:
                logger.debug(
                    "Multimodal PDF not embedded as image or file for %s "
                    "(enable AION_CHAT_MULTIMODAL_PDF_COMPATIBILITY_MODE or AION_CHAT_MULTIMODAL_PDF)",
                    rel,
                )

    if not parts:
        return ChatMessage.from_user(full_text)

    tail = full_text.strip() or "(See attached files.)"
    # Haystack docs: file/image parts first, then the text instruction.
    parts.append(tail)
    logger.info(
        "Multimodal user turn: session=%s embedded_native_parts=%s (max_files=%s)",
        session_id,
        n_embedded,
        max_parts,
    )
    return ChatMessage.from_user(content_parts=parts)


class AgentPipeline:
    def __init__(
        self,
        agent: Any,
        session_id: str,
        profile_name: str,
        user_id: str = "default",
        agent_mode: str = "normal",
    ):
        self.agent = agent
        self.session_id = session_id
        self.profile_name = profile_name
        self.user_id = user_id
        self.agent_mode = (agent_mode or "normal").strip().lower()

    def _format_attachments_block(
        self, attachments: Optional[List[Dict[str, Any]]]
    ) -> str:
        if not attachments:
            return ""
        lines = [
            "## Files available in the session (sandbox: write `workspace/*.py` + `sandbox_run_python_file` to run):"
        ]
        for a in attachments:
            rp = a.get("relative_path", "")
            orp = a.get("original_relative_path", "")
            on = a.get("original_name") or ""
            mime = a.get("mime") or ""
            extra = f" — `{on}`" if on else ""
            lines.append(f"- `{rp}`{extra} ({mime})")
            if orp and orp != rp:
                lines.append(f"  alias: `{orp}`")

        # If there are multiple files, add a strong prompt instruction to ensure the agent analyzes all of them
        if len(attachments) > 1:
            lines.append("")
            lines.append(
                "IMPORTANT: Multiple documents have been uploaded for this session. "
                "You MUST read, analyze, and consider ALL of them in your response. "
                "CRITICAL RULES:\n"
                "- NEVER process documents in parallel\n"
                "- ALWAYS process documents sequentially\n"
                "- Call ocr_file on one document at a time\n"
                "- Wait for the ocr_file call to complete before processing the next document\n"
                "- Do not ignore any of the uploaded documents\n"
                "Ensure you use your tools (like read_file, ocr, or custom scripts) to inspect all of them."
            )

        return "\n".join(lines) + "\n\n"

    async def _augment_user_input(self, user_input: str) -> str:
        """
        Dynamically augments the user prompt with turn-level metadata (last turn's tool execution summary and
        active workspace file manifest) for LLM consumption, keeping the DB/UI clean.
        """
        from datetime import datetime, timezone
        import json

        op_enabled = os.getenv("AION_MEMORY_OPERATIONAL_SUMMARY", "1").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        manifest_enabled = os.getenv("AION_MEMORY_WORKSPACE_MANIFEST", "1").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        orch_ctx_enabled = os.getenv("AION_ORCHESTRATION_CONTEXT", "1").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        if not op_enabled and not manifest_enabled and not orch_ctx_enabled:
            return user_input

        blocks = []

        if orch_ctx_enabled:
            try:
                from src.runtime.orchestration_tools import (
                    format_plan_tasks_excerpt,
                    resolve_active_plan_id,
                )
                from src.runtime import orchestration_db as odb

                plans = await odb.list_plans_for_session(self.session_id, limit=5)
                if plans:
                    active = await resolve_active_plan_id(self.session_id)
                    orch_lines = [
                        "### EXECUTION PLAN (orchestration DB — sidebar Plan)",
                        "Plans are **not** `workspace/execution_plan_*.md` files. "
                        "For task state: `list_session_execution_plans`, `get_execution_plan`, `mark_task_completed`.",
                    ]
                    for row in plans:
                        pid = row.get("plan_id", "")
                        tag = " **← active plan**" if active and pid == active else ""
                        orch_lines.append(
                            f"- `{pid}` status={row.get('status')} revision={row.get('revision')}{tag}"
                        )
                    if active:
                        rec = await odb.fetch_plan_record(active)
                        md = (
                            (
                                rec.get("approved_markdown")
                                or rec.get("draft_markdown")
                                or ""
                            )
                            if rec
                            else ""
                        ).strip()
                        if md:
                            excerpt = format_plan_tasks_excerpt(md, max_lines=24)
                            orch_lines.append(
                                f"\nActive plan `{active}` — use `mark_task_completed(task_id=...)` "
                                f"(plan_id optional) or `get_execution_plan()`:\n{excerpt}"
                            )
                    blocks.append("\n".join(orch_lines))
            except Exception as ex:
                logger.debug("orchestration context block skipped: %s", ex)

        # 1. TOOL OPERATIONAL SUMMARY
        if op_enabled:
            try:
                steps = await history_manager.get_last_assistant_steps(self.session_id)
                if steps:
                    summary_lines = []
                    for idx, step in enumerate(steps, 1):
                        name = step.get("name") or "tool"
                        type_ = step.get("type") or "tool"
                        is_err = bool(step.get("is_error"))

                        # Format input preview
                        raw_input = step.get("input") or ""
                        try:
                            # Try to pretty print JSON input
                            inp_obj = json.loads(raw_input)
                            if isinstance(inp_obj, dict):
                                # Clean up common long inputs or formatting
                                inp_desc = ", ".join(
                                    f"{k}={repr(v)[:150]}" for k, v in inp_obj.items()
                                )
                            else:
                                inp_desc = str(inp_obj)[:300]
                        except Exception:
                            inp_desc = raw_input[:300]

                        # Format output/error preview
                        raw_output = step.get("output") or ""
                        out_desc = ""
                        if is_err:
                            out_desc = f"ERROR: {raw_output[:500]}"
                        else:
                            if name in ("read_file", "view_file"):
                                out_desc = f"Successfully read file contents ({len(raw_output)} chars)."
                            elif name in (
                                "write_to_file",
                                "replace_file_content",
                                "multi_replace_file_content",
                            ):
                                out_desc = "Successfully updated file."
                            else:
                                out_desc = raw_output[:300]
                                if len(raw_output) > 300:
                                    out_desc += "..."

                        summary_lines.append(
                            f"{idx}. {name} ({type_}){' [error]' if is_err else ''}\n"
                            f"   parameters: `{inp_desc}`\n"
                            f"   result: {out_desc}"
                        )

                    blocks.append(
                        "### Previous turn tools\n"
                        "Summary of the last turn (avoid repeating identical reads or commands):\n\n"
                        + "\n".join(summary_lines)
                    )
            except Exception as ex:
                logger.warning("operational summary generation failed: %s", ex)

        # 2. WORKSPACE STATE MANIFEST
        if manifest_enabled:
            try:
                from src.session_workspace import session_root

                root_path = session_root(self.session_id)
                if root_path.exists():
                    files_info = []
                    # Recursively walk downloads/uploads/derived/workspace folders
                    for sub in ("uploads", "derived", "workspace"):
                        sub_dir = root_path / sub
                        if sub_dir.is_dir():
                            for p in sub_dir.rglob("*"):
                                if p.is_file():
                                    try:
                                        rel_path = p.relative_to(root_path)
                                        stat = p.stat()
                                        size_bytes = stat.st_size
                                        mtime = datetime.fromtimestamp(
                                            stat.st_mtime, tz=timezone.utc
                                        )

                                        # Human readable size
                                        if size_bytes < 1024:
                                            sz_str = f"{size_bytes} B"
                                        elif size_bytes < 1024 * 1024:
                                            sz_str = f"{size_bytes / 1024:.1f} KB"
                                        else:
                                            sz_str = (
                                                f"{size_bytes / (1024 * 1024):.1f} MB"
                                            )

                                        files_info.append(
                                            {
                                                "path": str(rel_path).replace(
                                                    "\\", "/"
                                                ),
                                                "size": sz_str,
                                                "size_bytes": size_bytes,
                                                "mtime": mtime,
                                            }
                                        )
                                    except Exception:
                                        pass

                    if files_info:
                        # Order by most recently modified
                        files_info.sort(key=lambda x: x["mtime"], reverse=True)

                        # Limit to top 15 files to avoid clutter
                        manifest_lines = []
                        for f in files_info[:15]:
                            manifest_lines.append(
                                f"- `{f['path']}` ({f['size']}, updated {f['mtime'].strftime('%Y-%m-%d %H:%M:%S UTC')})"
                            )
                        if len(files_info) > 15:
                            manifest_lines.append(
                                f"- ... and {len(files_info) - 15} more files in the sandbox."
                            )

                        blocks.append(
                            "### Workspace files\n"
                            "Recent sandbox files for this session:\n\n"
                            + "\n".join(manifest_lines)
                        )
            except Exception as ex:
                logger.warning("workspace manifest generation failed: %s", ex)

        if not blocks:
            return user_input

        context_header = (
            "--- runtime context (internal; do not quote to the user) ---\n\n"
            + "\n\n".join(blocks)
            + "\n--- end runtime context ---\n\n"
        )
        return context_header + user_input

    async def _pre_compact_transcript(
        self, transcript: str, *, head_count: int
    ) -> None:
        await ltm_orchestrator.precompact_flush(
            self.session_id,
            self.user_id,
            transcript,
        )
        await hook_registry.dispatch(
            "pre_compact",
            HookContext(
                event="pre_compact",
                tenant_id="default",
                conversation_id=self.session_id,
                user_id=self.user_id,
                payload={
                    "head_messages": head_count,
                    "transcript_chars": len(transcript),
                },
            ),
        )

    async def _reload_stm_window(
        self, exclude_message_ids: Optional[List[str]] = None
    ) -> List[ChatMessage]:
        from .settings import get_settings as _gs

        _s = _gs()
        max_turns = _s.stm_max_turns
        tbudget = str(_s.stm_token_budget) if _s.stm_token_budget is not None else None
        compressor = get_default_compressor()
        overhead = estimate_agent_overhead_tokens(self.agent)
        stm_msg_budget = compressor.max_message_tokens(overhead)
        env_tbudget = int(tbudget) if tbudget else None
        if env_tbudget is not None:
            stm_msg_budget = min(stm_msg_budget, env_tbudget)
        stm_char_limit = min(60_000, max(12_000, stm_msg_budget * 4))
        return await history_manager.get_window(
            self.session_id,
            self.profile_name,
            max_turns=max_turns,
            token_budget=stm_msg_budget,
            char_limit=stm_char_limit,
            exclude_message_ids=exclude_message_ids,
        )

    async def _apply_context_compression(
        self,
        messages: List[ChatMessage],
        *,
        force: bool = False,
        exclude_message_ids: Optional[List[str]] = None,
    ) -> tuple[List[ChatMessage], bool, bool]:
        """Ritorna (messages, did_compact, reloaded_from_db)."""
        enabled = os.getenv("AION_CONTEXT_COMPRESS_ENABLED", "1").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if not enabled and not force:
            return messages, False, False

        from src.runtime.user_language import (
            load_user_ui_language,
            resolve_compaction_language,
        )

        db_lang = await load_user_ui_language(self.user_id)
        user_lang = resolve_compaction_language(self.user_id, db_lang)

        compressor = get_default_compressor()
        overhead = estimate_agent_overhead_tokens(self.agent)
        stats = estimate_full_prompt_tokens(self.agent, messages)
        will_compact = force or compressor.should_compress(
            messages, fixed_overhead=overhead
        )
        log_context_budget(self.session_id, stats, will_compact=will_compact)

        if not will_compact:
            return messages, False, False

        persist = os.getenv("AION_CONTEXT_COMPRESS_PERSIST", "1").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        keep_last = compressor.keep_last
        before = stats["total"]

        async def _hook_messages(head: List[ChatMessage]) -> None:
            transcript = "\n".join(
                f"{m.role}: {chat_message_text(m)[:2500]}" for m in head
            )
            await self._pre_compact_transcript(transcript, head_count=len(head))

        async def _hook_transcript(transcript: str) -> None:
            await self._pre_compact_transcript(transcript, head_count=0)

        # Compattazione stile Claude: transcript completo dal DB (messaggi + timeline tool).
        try:
            db_rows = await history_manager.fetch_messages_for_compaction(
                self.session_id,
                profile_name=self.profile_name,
                keep_last_n=keep_last,
            )
        except Exception as exc:
            logger.warning("fetch_messages_for_compaction failed: %s", exc)
            db_rows = []

        if db_rows and (force or len(db_rows) >= 1):
            transcript = build_transcript_from_rows(
                [
                    CompactionTranscriptRow(
                        role=str(r.get("role") or "user"),
                        content=str(r.get("content") or ""),
                        timeline_json=r.get("timeline_json"),
                        reasoning=r.get("reasoning"),
                        tool_name=r.get("tool_name"),
                    )
                    for r in db_rows
                ]
            )
            if transcript.strip():
                logger.warning(
                    "context_compress db_start session=%s rows=%d transcript_chars=%d",
                    self.session_id[:8],
                    len(db_rows),
                    len(transcript),
                )
                summary = await compressor.summarize_transcript(
                    transcript,
                    pre_compression_hook=_hook_transcript,
                    lang=user_lang,
                )
                block = format_compaction_block(summary, source_messages=len(db_rows))
                if persist:
                    try:
                        await history_manager.persist_stm_compaction(
                            self.session_id,
                            profile_name=self.profile_name,
                            summary_content=block,
                            keep_last_n=keep_last,
                        )
                    except Exception as persist_exc:
                        logger.warning(
                            "context_compress persist failed session=%s: %s",
                            self.session_id[:8],
                            persist_exc,
                        )
                reloaded = await self._reload_stm_window(
                    exclude_message_ids=exclude_message_ids
                )
                after_stats = estimate_full_prompt_tokens(self.agent, reloaded)
                log_context_budget(
                    self.session_id,
                    after_stats,
                    will_compact=False,
                )
                logger.warning(
                    "context_compress db_done session=%s messages=%d total %d→%d",
                    self.session_id[:8],
                    len(reloaded),
                    before,
                    after_stats["total"],
                )
                if before > 0 and after_stats["total"] < before:
                    try:
                        from src.observability.metrics import (
                            aion_context_compression_ratio,
                        )

                        aion_context_compression_ratio.labels(
                            profile=self.profile_name
                        ).observe(after_stats["total"] / before)
                    except Exception:
                        pass
                return reloaded, True, True

        logger.warning(
            "context_compress memory_start session=%s force=%s messages=%d",
            self.session_id[:8],
            force,
            len(messages),
        )
        compressed = await compressor.compress_until_fits(
            messages,
            fixed_overhead=overhead,
            pre_compression_hook=_hook_messages,
            force=force,
            lang=user_lang,
        )
        after = compressor.total_with_overhead(compressed, overhead)
        logger.warning(
            "context_compress memory_done session=%s messages %d→%d tokens %d→%d",
            self.session_id[:8],
            len(messages),
            len(compressed),
            before,
            after,
        )
        if before > 0 and after < before:
            try:
                from src.observability.metrics import aion_context_compression_ratio

                aion_context_compression_ratio.labels(
                    profile=self.profile_name
                ).observe(after / before)
            except Exception:
                pass
        if after < before and persist:
            summary_text = chat_message_text(compressed[0])
            if "[AION COMPACTION" in summary_text or "[CONTEXT SUMMARY" in summary_text:
                try:
                    await history_manager.persist_stm_compaction(
                        self.session_id,
                        profile_name=self.profile_name,
                        summary_content=summary_text,
                        keep_last_n=keep_last,
                    )
                except Exception as persist_exc:
                    logger.warning(
                        "context_compress persist failed session=%s: %s",
                        self.session_id[:8],
                        persist_exc,
                    )
        return compressed, True, False

    @track(name="run_stream", ignore_arguments=["self"])
    async def run_stream(
        self,
        user_input: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        turn_attachments: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        user_message_id: Optional[str] = None,
        assistant_message_id: Optional[str] = None,
        message_source: str = "user_input",
        web_search_enabled: Optional[bool] = None,
        web_search_restrict_hosts: Optional[List[str]] = None,
        sql_query_project: Optional[str] = None,
        plan_id: Optional[str] = None,
        plan_execution_task_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        logger.info(">>> [0] ENTERING run_stream for session %s", self.session_id)
        from src.runtime.web_search_context import (
            WebSearchRequestContext,
            reset_web_search_request_context,
            set_web_search_request_context,
        )

        from .settings import get_settings as _gs

        opt_req = _gs().web_search_require_client_opt_in
        if web_search_enabled is None:
            _wse = not opt_req
        else:
            _wse = bool(web_search_enabled)
        _ws_hosts = tuple((web_search_restrict_hosts or [])[:20])
        _web_tok = set_web_search_request_context(
            WebSearchRequestContext(enabled=_wse, restrict_hosts=_ws_hosts)
        )
        from src.runtime.agent_mode_resolve import resolve_agent_mode

        effective_agent_mode = resolve_agent_mode(
            self.agent_mode,
            plan_mode=None,
            message_source=message_source,
        )
        _skip_plan_turn_early = (message_source or "").strip() in (
            "internal_trigger",
            "scheduled_trigger",
        )
        plan_controller = None
        if effective_agent_mode == "plan" and not _skip_plan_turn_early:
            from src.runtime.plan_engine import PlanModeController

            plan_controller = PlanModeController()

        # Opik self-hosted telemetry tracking
        try:
            from src.observability.opik_setup import OPIK_AVAILABLE

            if OPIK_AVAILABLE:
                from opik.opik_context import update_current_trace
                from src.observability.opik_setup import get_or_create_prompt

                prompt_name = (
                    f"profile-{self.profile_name.replace(' ', '_').lower()}-prompt"
                )
                system_prompt_template = (
                    self.agent.system_prompt
                    if (
                        hasattr(self, "agent")
                        and self.agent
                        and hasattr(self.agent, "system_prompt")
                    )
                    else f"Instructions for the agent based on profile {self.profile_name}"
                )
                prompt_obj = get_or_create_prompt(
                    prompt_name=prompt_name,
                    template_content=system_prompt_template
                    + "\n\nUser request: {{user_input}}",
                )
                update_current_trace(
                    thread_id=self.session_id,
                    tags=[self.profile_name, "AION-Agent-Turn"],
                    metadata={
                        "session_id": self.session_id,
                        "user_id": self.user_id,
                        "profile_name": self.profile_name,
                        "model": (os.getenv("AION_MODEL") or "").strip() or "unknown",
                        "user_input": user_input,
                    },
                    prompts=[prompt_obj],
                )
        except Exception as opik_err:
            logger.warning(
                "Errore durante l'inizializzazione del tracciamento Opik: %s", opik_err
            )

        from .settings import get_settings as _gs

        otel_enabled = _gs().otel_enabled
        span = None
        otel_token = None
        if otel_enabled:
            try:
                from opentelemetry import trace, context
                from opentelemetry.trace import set_span_in_context

                tracer = trace.get_tracer("aion.pipeline")
                parent_span = trace.get_current_span()
                if parent_span and parent_span.is_recording():
                    parent_span.set_attribute("aion.session_id", self.session_id or "")
                    parent_span.set_attribute("aion.user_id", self.user_id or "")
                    parent_span.set_attribute("aion.profile", self.profile_name or "")
                    parent_span.set_attribute("aion.tenant_id", "default")
                    parent_span.set_attribute("aion.user_question", user_input or "")

                span = tracer.start_span("conversation.turn")
                span.set_attribute("aion.session_id", self.session_id or "")
                span.set_attribute("aion.user_id", self.user_id or "")
                span.set_attribute("aion.profile", self.profile_name or "")
                span.set_attribute("aion.tenant_id", "default")
                span.set_attribute("aion.user_question", user_input or "")
                ctx = set_span_in_context(span)
                otel_token = context.attach(ctx)
            except Exception as e:
                logger.warning("Errore inizializzazione span OTel: %s", e)

        try:
            _turn_start_time = time.monotonic()
            _turn_status = "ok"
            _turn_error_type = None
            _llm_steps_done = 0
            _accumulated_prompt_tokens = 0
            _accumulated_completion_tokens = 0
            _accumulated_reasoning_tokens = 0

            from src.runtime.timeline_builder import TimelineBuilder

            timeline_builder = TimelineBuilder()

            def _track_sse(out: Dict[str, Any]) -> Dict[str, Any]:
                if isinstance(out, dict) and out.get("type"):
                    timeline_builder.apply_chunk(out)
                return out

            from src.runtime.turn_message_ids import ensure_turn_message_ids

            user_message_id, assistant_message_id = ensure_turn_message_ids(
                user_message_id, assistant_message_id
            )
            yield _track_sse(
                {
                    "type": "turn_started",
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id,
                }
            )
            if plan_controller is not None:
                yield _track_sse(plan_controller.sse_phase("clarifying"))

            _msg_src = (message_source or "user_input").strip()
            user_role = (
                "user"
                if _msg_src in ("user_input", "scheduled_trigger")
                else "internal"
            )
            _plan_meta_json = _plan_turn_metadata_json(plan_id, plan_execution_task_id)

            try:
                await history_manager.upsert_message_content(
                    self.session_id,
                    user_message_id,
                    user_role,
                    user_input,
                    profile_name=self.profile_name,
                    user_id=self.user_id,
                    metadata_json=_plan_meta_json,
                )
            except Exception as user_persist_exc:
                logger.warning("Early user message upsert failed: %s", user_persist_exc)

            persist_atts_early = (
                turn_attachments if turn_attachments is not None else attachments
            )
            if persist_atts_early:
                for a in persist_atts_early:
                    rp = a.get("relative_path")
                    if not rp:
                        continue
                    on = a.get("original_name") or Path(rp).name
                    mime = a.get("mime") or "application/octet-stream"
                    try:
                        await history_manager.add_attachment(
                            self.session_id,
                            storage_key=rp,
                            original_name=on,
                            mime=mime,
                            size_bytes=0,
                            kind="user_attachment",
                            message_id=user_message_id,
                        )
                    except Exception as att_exc:
                        logger.warning(
                            "Early user attachment persist failed: %s", att_exc
                        )

            logger.info(
                "--- [START] Pipeline Turn for session %s mode=%s (stored=%s source=%s) ---",
                self.session_id,
                effective_agent_mode,
                self.agent_mode,
                message_source,
            )
            import os as _os_qm

            from src.runtime.sql_query_memory_context import (
                clear_sql_qm_turn_context,
                set_sql_qm_turn_context,
            )

            _qm_project = (
                sql_query_project
                or _os_qm.getenv("AION_SQL_QM_DEFAULT_PROJECT")
                or "default"
            ).strip()
            if not sql_query_project:
                try:
                    from src.memory.sql_query_memory.conversation_project import (
                        get_conversation_sql_project,
                    )

                    conv_proj = await get_conversation_sql_project(self.session_id)
                    if conv_proj:
                        from src.runtime.sql_query_project_resolve import (
                            resolve_sql_query_project,
                        )

                        _qm_project = resolve_sql_query_project(
                            request_project=None,
                            conversation_project=conv_proj,
                        )
                except Exception:
                    pass
            from src.agent_profile import profile_manager as _pm_qm

            _prof_row = _pm_qm.get_profile(self.profile_name)
            _qm_profile_slug = (
                _prof_row.slug
                if _prof_row
                else self.profile_name.replace(" ", "_").lower()
            )
            try:
                from src.runtime.query_memory_hooks import (
                    profile_has_memory_capability_by_slug,
                )
                from src.runtime.sql_query_project_scope import (
                    verify_user_project_access,
                )

                if profile_has_memory_capability_by_slug(_qm_profile_slug):
                    _acc_err = await verify_user_project_access(
                        project_slug=_qm_project,
                        tenant_id=(
                            _os_qm.getenv("AION_DEFAULT_TENANT_ID") or "default"
                        ).strip()
                        or "default",
                        user_id=self.user_id,
                        profile_slug=_qm_profile_slug,
                    )
                    if _acc_err:
                        yield {"type": "error", "content": _acc_err}
                        return
            except Exception as acc_exc:
                logger.debug("project access gate skipped: %s", acc_exc)
            # #region agent log
            _agent_debug_log(
                "H3",
                "run_stream:start",
                "turn_started",
                {
                    "session_id": self.session_id[:12],
                    "profile": self.profile_name,
                    "reasoning_effort": reasoning_effort,
                    "thinking_enabled": reasoning_effort != "min",
                    "max_agent_steps": getattr(self.agent, "max_agent_steps", None),
                    "user_input_preview": (user_input or "")[:80],
                },
            )
            # #endregion
            loop = asyncio.get_running_loop()
            set_event_loop(loop)

            # Kill switch per il thread dell'agente
            stop_event = threading.Event()

            # 1. Check for slash commands
            if (user_input or "").strip().startswith("/"):
                from src.runtime.slash import SlashContext, slash_router

                sr = await slash_router.route(
                    user_input.strip(),
                    SlashContext(
                        raw=user_input.strip(),
                        conversation_id=self.session_id,
                        user_id=self.user_id,
                        profile_name=self.profile_name,
                    ),
                )
                if sr.handled:
                    for ev in sr.sse_events or []:
                        yield ev
                    msg = sr.message or "(nessun output)"
                    yield {"type": "token", "content": msg}
                    yield {"type": "final", "text": msg}
                    return

            # Check LLM connection before database persistence and model invocation
            llm_url = ""
            api_key = ""
            if (
                hasattr(self, "agent")
                and self.agent
                and hasattr(self.agent, "chat_generator")
            ):
                generator = self.agent.chat_generator
                if generator:
                    if hasattr(generator, "api_base_url") and generator.api_base_url:
                        llm_url = generator.api_base_url
                    if hasattr(generator, "api_key") and generator.api_key:
                        from haystack.utils import Secret

                        if isinstance(generator.api_key, Secret):
                            resolved = generator.api_key.resolve_value()
                            if resolved:
                                api_key = resolved
                        elif isinstance(generator.api_key, str):
                            api_key = generator.api_key

            # Fallback to env variables if not found/resolved from the generator
            if not llm_url:
                llm_url = os.getenv("AION_API_URL", "")
            if not api_key or api_key == "placeholder-token":
                api_key = os.getenv("AION_LLM_API_KEY", "placeholder-token")

            if not llm_url:
                yield {
                    "type": "error",
                    "content": "Configuration error: LLM URL is not set",
                }
                return

            from src.runtime.llm_health import check_llm_connection

            is_connected, err_msg = await asyncio.to_thread(
                check_llm_connection, llm_url, api_key
            )
            if not is_connected:
                logger.error("LLM connection check failed for %s: %s", llm_url, err_msg)
                yield {"type": "error", "content": err_msg}
                return

            await hook_registry.dispatch(
                "on_user_message",
                HookContext(
                    event="on_user_message",
                    tenant_id="default",
                    conversation_id=self.session_id,
                    user_id=self.user_id,
                    payload={"message": user_input, "attachments": attachments or []},
                ),
            )

            # 2. Context preparation (delegated to build_turn_context)
            logger.info(">>> [1] Preparing context for session %s", self.session_id)
            from src.runtime.turn.turn_context import (
                build_turn_context as _build_turn_context,
            )

            _ctx_sse_events: List[Dict[str, Any]] = []
            _turn_ctx = await _build_turn_context(
                self,
                user_input=user_input,
                attachments=attachments,
                turn_attachments=turn_attachments,
                message_source=message_source,
                effective_agent_mode=effective_agent_mode,
                sql_query_project=sql_query_project,
                plan_execution_task_id=plan_execution_task_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                track_sse_callback=_ctx_sse_events.append,
            )
            for _ctx_evt in _ctx_sse_events:
                yield _track_sse(_ctx_evt)
            messages: List[ChatMessage] = _turn_ctx.messages
            augmented_user = _turn_ctx.augmented_user
            _prompt_inject_layers = _turn_ctx.prompt_inject_layers
            _qm_project = _turn_ctx.qm_project
            _qm_profile_slug = _turn_ctx.qm_profile_slug
            turn_context_stats = _turn_ctx.context_stats
            # 3. Signal stream active (agent hasn't started yet)
            if user_message_id and assistant_message_id:
                await redis_set_stream_active(
                    self.session_id,
                    assistant_message_id=assistant_message_id,
                    user_message_id=user_message_id,
                    profile_name=self.profile_name,
                )

            from src.runtime.prompt_snapshot import (
                build_prompt_snapshot,
                prompt_debug_enabled,
                store_prompt_snapshot,
                track_prepend_layer,
            )

            # 4. Stream setup
            from src.runtime.plan_mode import (
                plan_mode_tool_first,
                plan_text_parser_enabled,
            )

            from .settings import get_settings as _gs

            strategy = _gs().artifact_strategy.lower()
            if strategy == "tool":
                base_parser = NoOpArtifactParser()
            elif strategy == "markdown":
                base_parser = MarkdownArtifactStreamParser()
            else:
                base_parser = XMLArtifactStreamParser()
            _use_plan_text_parser = plan_text_parser_enabled() or (
                effective_agent_mode == "plan" and not plan_mode_tool_first()
            )
            if _use_plan_text_parser:
                artifact_parser = PlanTagInterceptorParser(base_parser)
            else:
                artifact_parser = base_parser

            artifact_manager = ArtifactManager(self.session_id)
            queue: asyncio.Queue = asyncio.Queue()
            tool_q = tool_event_bus.subscribe(self.session_id)

            def _artifact_end_payload(pe, path: Path, version: int) -> Dict[str, Any]:
                return {
                    "identifier": pe.artifact_id,
                    "type": pe.artifact_type or "text",
                    "title": pe.artifact_title,
                    "path": str(path.relative_to(artifact_manager._root)),
                    "version": version,
                    "saved": True,
                }

            async def listen_tool_events():
                try:
                    while True:
                        event = await tool_q.get()
                        await queue.put({"type": "tool_event", "event": event})
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error("Tool listener crashed: %s", e)
                finally:
                    tool_event_bus.unsubscribe(self.session_id, tool_q)

            tool_listener_task = asyncio.create_task(listen_tool_events())
            gen_kw = generation_kwargs_for_agent(self.agent, reasoning_effort)

            if prompt_debug_enabled():
                _prompt_snapshot = build_prompt_snapshot(
                    self.agent,
                    messages,
                    inject_layers=_prompt_inject_layers,
                    turn_meta={
                        "session_id": self.session_id,
                        "profile": self.profile_name,
                        "agent_mode": effective_agent_mode,
                        "message_source": message_source,
                        "user_message_id": user_message_id,
                        "assistant_message_id": assistant_message_id,
                        "sql_query_project": _qm_project,
                        "reasoning_effort": reasoning_effort,
                    },
                    generation_kwargs=gen_kw,
                )
                store_prompt_snapshot(
                    self.session_id,
                    _prompt_snapshot,
                    assistant_message_id=assistant_message_id,
                )
                yield _track_sse(
                    {
                        "type": "prompt_snapshot",
                        "assistant_message_id": assistant_message_id,
                        "snapshot": _prompt_snapshot,
                    }
                )

            async def _run_agent_async(msgs: List[ChatMessage]) -> Any:
                _turn_pid = (
                    plan_controller.plan_id if plan_controller is not None else None
                )
                set_context(
                    self.session_id,
                    loop,
                    queue,
                    stop_event,
                    turn_plan_id=_turn_pid,
                )
                set_turn_runtime(
                    session_id=self.session_id,
                    loop=loop,
                    queue=queue,
                    stop_event=stop_event,
                    agent=self.agent,
                    profile_name=self.profile_name,
                    user_id=self.user_id,
                )
                _agent_debug_log(
                    "H3",
                    "_run_agent_async:start",
                    "agent_async_started",
                    {
                        "session_id": self.session_id[:12],
                        "message_count": len(msgs),
                        "agent_mode": effective_agent_mode,
                    },
                )
                try:
                    res = await self.agent.run_async(
                        msgs,
                        streaming_callback=haystack_agent_streaming_callback_async,
                        generation_kwargs=gen_kw,
                    )
                    _agent_debug_log(
                        "H1",
                        "_run_agent_async:return",
                        "agent_run_ok",
                        {
                            "session_id": self.session_id[:12],
                            "result_type": type(res).__name__,
                        },
                    )
                    return res
                except Exception as e:
                    _agent_debug_log(
                        "H1",
                        "_run_agent_async:except",
                        "agent_run_exception",
                        {
                            "session_id": self.session_id[:12],
                            "exc_type": type(e).__name__,
                            "exc_msg": str(e)[:500],
                            "stop_event": bool(stop_event.is_set()),
                        },
                    )
                    if not stop_event.is_set():
                        logger.error("Agent.run_async failed: %s", e)
                        logger.error(traceback.format_exc())
                        if is_context_length_error(e):
                            queue.put_nowait(
                                {"type": "context_length_error", "content": str(e)}
                            )
                        else:
                            queue.put_nowait({"type": "error", "content": str(e)})
                finally:
                    clear_turn_runtime()
                    clear_context()
                    queue.put_nowait({"type": "done"})

            def _run_agent_sync(msgs: List[ChatMessage]) -> Any:
                _turn_pid = (
                    plan_controller.plan_id if plan_controller is not None else None
                )
                set_context(
                    self.session_id,
                    loop,
                    queue,
                    stop_event,
                    turn_plan_id=_turn_pid,
                )
                set_turn_runtime(
                    session_id=self.session_id,
                    loop=loop,
                    queue=queue,
                    stop_event=stop_event,
                    agent=self.agent,
                    profile_name=self.profile_name,
                    user_id=self.user_id,
                )
                _agent_debug_log(
                    "H3",
                    "_run_agent_sync:start",
                    "agent_thread_started",
                    {
                        "session_id": self.session_id[:12],
                        "message_count": len(msgs),
                        "agent_mode": effective_agent_mode,
                    },
                )
                try:
                    res = self.agent.run(
                        msgs,
                        streaming_callback=haystack_agent_streaming_callback,
                        generation_kwargs=gen_kw,
                    )
                    _agent_debug_log(
                        "H1",
                        "_run_agent_sync:return",
                        "agent_run_ok",
                        {
                            "session_id": self.session_id[:12],
                            "result_type": type(res).__name__,
                        },
                    )
                    return res
                except Exception as e:
                    _agent_debug_log(
                        "H1",
                        "_run_agent_sync:except",
                        "agent_run_exception",
                        {
                            "session_id": self.session_id[:12],
                            "exc_type": type(e).__name__,
                            "exc_msg": str(e)[:500],
                            "stop_event": bool(stop_event.is_set()),
                        },
                    )
                    if not stop_event.is_set():
                        logger.error("Agent.run crashed in thread: %s", e)
                        logger.error(traceback.format_exc())
                        if is_context_length_error(e):
                            loop.call_soon_threadsafe(
                                queue.put_nowait,
                                {"type": "context_length_error", "content": str(e)},
                            )
                        else:
                            loop.call_soon_threadsafe(
                                queue.put_nowait, {"type": "error", "content": str(e)}
                            )
                finally:
                    clear_turn_runtime()
                    clear_context()
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "done"})

            # 5. Main stream loop
            logger.info(">>> [5] Starting agent thread...")
            agent_messages = list(messages)
            from src.runtime.agent_exec import run_agent_turn

            agent_task = asyncio.create_task(
                run_agent_turn(
                    agent_messages,
                    sync_runner=_run_agent_sync,
                    async_runner=_run_agent_async,
                )
            )
            keepalive_task: Optional[asyncio.Task] = None
            keepalive_sec = float(os.getenv("AION_SSE_KEEPALIVE_SEC", "15"))
            if keepalive_sec > 0:

                async def _sse_keepalive() -> None:
                    while not agent_task.done():
                        await asyncio.sleep(keepalive_sec)
                        if agent_task.done():
                            break
                        await queue.put({"type": "keepalive"})

                keepalive_task = asyncio.create_task(_sse_keepalive())
            full_response, full_reasoning, tool_calls_log = [], [], []
            from src.runtime.turn.turn_guards import TurnGuards
            from src.runtime.turn_budget import TurnBudget

            turn_guards = TurnGuards(
                message_source=_msg_src,
                loop_time_fn=loop.time,
                budget=TurnBudget.load(
                    message_source=_msg_src,
                    reasoning_effort=reasoning_effort,
                ),
            )
            max_reasoning_chars = turn_guards.max_reasoning_chars
            max_reasoning_events = turn_guards.max_reasoning_events
            max_tool_events = turn_guards.max_tool_events
            max_tool_calls = turn_guards.max_tool_calls
            max_stream_events = turn_guards.max_stream_events
            max_control_events = turn_guards.max_control_events
            max_output_events = turn_guards.max_output_events
            max_output_chars = turn_guards.max_output_chars
            no_progress_timeout = turn_guards.no_progress_timeout
            min_reasoning_chars_without_tool = (
                turn_guards.min_reasoning_chars_without_tool
            )
            max_reasoning_events_without_tool = (
                turn_guards.max_reasoning_events_without_tool
            )
            reasoning_hard_stop = turn_guards.reasoning_hard_stop
            single_orch_channel = os.getenv(
                "AION_ORCH_EVENT_SINGLE_CHANNEL", "1"
            ).strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            is_streaming = False
            reasoning_chars = 0
            reasoning_events = 0
            tool_events = 0
            tool_calls = 0
            stream_events = 0
            control_events = 0
            output_events = 0
            output_chars = 0
            stop_reason = "completed"
            last_progress_at = turn_guards.state.last_progress_at
            reasoning_guard_logged = turn_guards.state.reasoning_guard_logged
            reasoning_no_tool_warned = turn_guards.state.reasoning_no_tool_warned
            artifact_parse_hits = 0
            artifact_salvage = 0
            plan_intercepts = 0
            plan_finalize_source: Optional[str] = None
            plan_text_fallback_count = 0
            raw_token_fallback_chunks = 0
            _skip_plan_turn = _skip_plan_turn_early
            from src.runtime.turn.turn_persistence import TurnPersistence

            turn_persist = TurnPersistence(
                session_id=self.session_id,
                history_manager=history_manager,
                assistant_message_id=assistant_message_id,
                metadata_json=_plan_meta_json,
            )
            pending_write_artifacts: Dict[str, Dict[str, Any]] = {}
            pending_db_steps = turn_persist.pending_db_steps
            pending_db_attachments = turn_persist.pending_db_attachments
            assistant_message_persisted = turn_persist.assistant_message_persisted
            turn_new_messages: List[Any] = []
            turn_context_stats: Dict[str, Any] = {}

            def queue_attachment(**kwargs) -> None:
                turn_persist.queue_attachment(**kwargs)

            def queue_tool_step(
                evt: Dict[str, Any], *, is_error: bool = False, is_start: bool = False
            ) -> None:
                turn_persist.queue_tool_step(evt, is_error=is_error, is_start=is_start)

            async def persist_pending_turn_records(
                message_id: Optional[str],
                *,
                only_new: bool = False,
                include_attachments: bool = True,
            ) -> None:
                await turn_persist.persist_pending_turn_records(
                    message_id,
                    only_new=only_new,
                    include_attachments=include_attachments,
                )

            async def _flush_assistant_stream_content(*, force: bool = False) -> None:
                nonlocal assistant_message_persisted
                import json

                tl_json = None
                if timeline_builder and timeline_builder.segments:
                    try:
                        tl_json = json.dumps(
                            timeline_builder.segments, ensure_ascii=False
                        )
                    except Exception:
                        pass
                await turn_persist.flush_assistant_stream_content(
                    full_response=full_response,
                    full_reasoning=full_reasoning,
                    profile_name=self.profile_name,
                    user_id=self.user_id,
                    loop_time=loop.time(),
                    force=force,
                    timeline_json=tl_json,
                )
                assistant_message_persisted = turn_persist.assistant_message_persisted

            if assistant_message_id:
                try:
                    inserted = await history_manager.upsert_message_content(
                        self.session_id,
                        assistant_message_id,
                        "assistant",
                        "",
                        profile_name=self.profile_name,
                        user_id=self.user_id,
                        metadata_json=_plan_meta_json,
                    )
                    if inserted:
                        assistant_message_persisted = True
                except Exception as upsert_exc:
                    logger.warning(
                        "assistant placeholder upsert failed: %s", upsert_exc
                    )

            logger.info(">>> [6] Entering stream loop...")
            _use_stream_loop_v2 = _gs().stream_loop_v2
            try:
                if _use_stream_loop_v2:
                    from src.runtime.stream.loop import StreamLoop
                    from src.runtime.stream.demux import StreamDemux

                    _sl_demux = StreamDemux()
                    _stream_loop = StreamLoop(
                        queue=queue,
                        stop_event=stop_event,
                        loop=loop,
                        turn_guards=turn_guards,
                        artifact_parser=artifact_parser,
                        artifact_manager=artifact_manager,
                        turn_persist=turn_persist,
                        session_id=self.session_id,
                        profile_name=self.profile_name,
                        user_id=self.user_id,
                        assistant_message_id=assistant_message_id,
                        plan_controller=plan_controller,
                        message_source=message_source,
                        plan_text_parser_enabled_fn=(
                            lambda: (
                                plan_text_parser_enabled()
                                or (
                                    effective_agent_mode == "plan"
                                    and not plan_mode_tool_first()
                                )
                            )
                        ),
                        demux=_sl_demux,
                        track_sse=_track_sse,
                        timeline_builder=timeline_builder,
                    )
                    async for _sl_evt in _stream_loop.consume():
                        yield _sl_evt
                    # Sync mutable state back to local variables for post-loop code
                    full_response = _stream_loop.full_response
                    full_reasoning = _stream_loop.full_reasoning
                    tool_calls_log = _stream_loop.tool_calls_log
                    stop_reason = _stream_loop.stop_reason
                    tool_calls = _stream_loop.tool_calls
                    tool_events = _stream_loop.tool_events
                    stream_events = _stream_loop.stream_events
                    control_events = _stream_loop.control_events
                    output_events = _stream_loop.output_events
                    output_chars = _stream_loop.output_chars
                    reasoning_chars = _stream_loop.reasoning_chars
                    reasoning_events = _stream_loop.reasoning_events
                    artifact_parse_hits = _stream_loop.artifact_parse_hits
                    artifact_salvage = _stream_loop.artifact_salvage
                    plan_intercepts = _stream_loop.plan_intercepts
                    raw_token_fallback_chunks = _stream_loop.raw_token_fallback_chunks
                    pending_write_artifacts = _stream_loop.pending_write_artifacts
                    assistant_message_persisted = (
                        turn_persist.assistant_message_persisted
                    )
                    _llm_steps_done = _stream_loop._llm_steps_done
                else:
                    async with asyncio.timeout(turn_guards.turn_timeout):
                        while True:
                            # PROACTIVE SYNC: If queue is empty and we're not expecting tokens, signal we're caught up
                            if queue.empty() and not is_streaming:
                                StreamSync.mark_caught_up(self.session_id)

                            chunk = await queue.get()
                            stream_events += 1
                            ctype = str(chunk.get("type") or "")
                            evt_for_counter = chunk.get("event") or {}
                            c_inc, o_inc = _chunk_counters(
                                ctype, str(evt_for_counter.get("type") or "")
                            )
                            control_events += c_inc
                            output_events += o_inc
                            if ctype in ("token", "artifact_content"):
                                output_chars += len(str(chunk.get("content") or ""))
                            if ctype == "reasoning":
                                output_chars += len(str(chunk.get("reasoning") or ""))

                            if (
                                max_stream_events > 0
                                and stream_events > max_stream_events
                            ):
                                stop_event.set()
                                stop_reason = "stream_events_limit"
                                msg = (
                                    "Interrotto automaticamente: superato budget eventi turno "
                                    f"({stream_events}/{max_stream_events})."
                                )
                                logger.warning("Hard-stop loop guard: %s", msg)
                                yield {"type": "error", "content": msg}
                                break
                            if (
                                max_control_events > 0
                                and control_events > max_control_events
                            ):
                                stop_event.set()
                                stop_reason = "control_events_limit"
                                msg = (
                                    "Interrotto automaticamente: troppi eventi di controllo nel turno "
                                    f"({control_events}/{max_control_events})."
                                )
                                logger.warning("Hard-stop control guard: %s", msg)
                                yield {"type": "error", "content": msg}
                                break
                            if (
                                max_output_events > 0
                                and output_events > max_output_events
                            ):
                                stop_event.set()
                                stop_reason = "output_events_limit"
                                msg = (
                                    "Interrotto automaticamente: superato limite output eventi turno "
                                    f"({output_events}/{max_output_events})."
                                )
                                logger.warning("Hard-stop output-event guard: %s", msg)
                                yield {"type": "error", "content": msg}
                                break
                            if max_output_chars > 0 and output_chars > max_output_chars:
                                stop_event.set()
                                stop_reason = "output_chars_limit"
                                msg = (
                                    "Interrotto automaticamente: superato limite output caratteri turno "
                                    f"({output_chars}/{max_output_chars})."
                                )
                                logger.warning("Hard-stop output-char guard: %s", msg)
                                yield {"type": "error", "content": msg}
                                break
                            if (
                                no_progress_timeout > 0
                                and (loop.time() - last_progress_at)
                                > no_progress_timeout
                            ):
                                stop_event.set()
                                stop_reason = "no_progress_timeout"
                                msg = (
                                    "Interrotto automaticamente: nessun progresso rilevato nel turno "
                                    f"({int(no_progress_timeout)}s)."
                                )
                                _agent_debug_log(
                                    "H2",
                                    "run_stream:no_progress",
                                    "no_progress_timeout",
                                    {
                                        "session_id": self.session_id[:12],
                                        "idle_sec": round(
                                            loop.time() - last_progress_at, 1
                                        ),
                                        "tool_calls": tool_calls,
                                        "output_chars": output_chars,
                                    },
                                )
                                logger.warning("Hard-stop no-progress guard: %s", msg)
                                yield {"type": "error", "content": msg}
                                break
                            # print(f">>> [DEBUG_QUEUE] Received chunk: {chunk.get('type')}")
                            if chunk.get("type") == "keepalive":
                                last_progress_at = loop.time()
                                continue

                            if chunk.get("type") == "done":
                                _agent_debug_log(
                                    "H4",
                                    "run_stream:done",
                                    "queue_done_received",
                                    {
                                        "session_id": self.session_id[:12],
                                        "full_response_len": len(
                                            "".join(full_response)
                                        ),
                                        "stop_reason": stop_reason,
                                        "tool_calls": tool_calls,
                                    },
                                )
                                break
                            if chunk.get("type") == "error":
                                _agent_debug_log(
                                    "H1",
                                    "run_stream:queue_error",
                                    "queue_error_chunk",
                                    {
                                        "session_id": self.session_id[:12],
                                        "content": str(chunk.get("content") or "")[
                                            :300
                                        ],
                                    },
                                )
                                yield _track_sse(chunk)
                                break

                            if chunk.get("type") == "llm_call":
                                _llm_steps_done += 1
                                continue

                            if chunk.get("type") == "token":
                                is_streaming = True
                                had_only_text = True
                                raw_token = chunk.get("content") or ""
                                text_emitted = False
                                for pe in artifact_parser.feed(raw_token):
                                    if pe.event == ArtifactEvent.TEXT:
                                        if pe.content:
                                            full_response.append(pe.content)
                                            text_emitted = True
                                        last_progress_at = loop.time()
                                        yield _track_sse(
                                            {"type": "token", "content": pe.content}
                                        )
                                        await _flush_assistant_stream_content()
                                    elif pe.event == ArtifactEvent.ARTIFACT_START:
                                        had_only_text = False
                                        artifact_parse_hits += 1
                                        if (
                                            pe.artifact_type or ""
                                        ).strip().lower() == "plan":
                                            plan_intercepts += 1
                                        yield _track_sse(
                                            {
                                                "type": "artifact_start",
                                                "artifact": {
                                                    "identifier": pe.artifact_id,
                                                    "type": pe.artifact_type,
                                                    "title": pe.artifact_title,
                                                    "auto_execute": pe.auto_execute,
                                                },
                                            }
                                        )
                                    elif pe.event == ArtifactEvent.ARTIFACT_CONTENT:
                                        had_only_text = False
                                        if pe.content:
                                            last_progress_at = loop.time()
                                        yield _track_sse(
                                            {
                                                "type": "artifact_content",
                                                "content": pe.content,
                                                "artifact_id": pe.artifact_id,
                                            }
                                        )
                                    elif pe.event == ArtifactEvent.ARTIFACT_END:
                                        had_only_text = False
                                        if _is_plan_artifact_payload(
                                            pe.artifact_id or "",
                                            pe.artifact_type or "",
                                            pe.content or "",
                                        ):
                                            _pid = _resolve_turn_plan_id(
                                                plan_controller, pe.artifact_id
                                            )
                                            pending = await _setup_plan_artifact_chunk(
                                                session_id=self.session_id,
                                                user_id=self.user_id,
                                                artifact_id=_pid,
                                                markdown_content=pe.content or "",
                                            )
                                            yield _track_sse(
                                                {
                                                    "type": "artifact_end",
                                                    "artifact": _plan_artifact_sse_end(
                                                        pe, plan_id=_pid
                                                    ),
                                                }
                                            )
                                            if pending:
                                                yield _track_sse(pending)
                                        else:
                                            path, version = artifact_manager.save(
                                                pe.artifact_id,
                                                pe.content,
                                                pe.artifact_type,
                                                pe.filename,
                                            )
                                            res = {
                                                "type": "artifact_end",
                                                "artifact": _artifact_end_payload(
                                                    pe, path, version
                                                ),
                                            }
                                            if pe.auto_execute and path.suffix == ".py":
                                                res["artifact"]["execution"] = (
                                                    artifact_manager.auto_execute_sandboxed(
                                                        path
                                                    )
                                                )
                                            queue_attachment(
                                                storage_key=str(
                                                    path.relative_to(
                                                        artifact_manager._root
                                                    )
                                                ),
                                                original_name=pe.filename
                                                or pe.artifact_id,
                                                mime=pe.artifact_type or "text/plain",
                                                size_bytes=len(pe.content or ""),
                                            )
                                            yield _track_sse(res)
                                if plan_controller:
                                    _prog = plan_controller.maybe_progress_sse(
                                        "".join(full_response)
                                    )
                                    if _prog:
                                        yield _track_sse(_prog)
                                if (
                                    had_only_text
                                    and not text_emitted
                                    and raw_token
                                    and not getattr(
                                        artifact_parser,
                                        "is_suppressing_tokens",
                                        lambda: False,
                                    )()
                                ):
                                    _suppress_plan_token = False
                                    if (
                                        plan_controller is not None
                                        and plan_text_parser_enabled()
                                    ):
                                        from src.runtime.plan_engine import (
                                            should_suppress_plan_token,
                                        )

                                        _suppress_plan_token = (
                                            should_suppress_plan_token(
                                                raw_token, "".join(full_response)
                                            )
                                        )
                                    full_response.append(raw_token)
                                    raw_token_fallback_chunks += 1
                                    if not _suppress_plan_token:
                                        last_progress_at = loop.time()
                                        yield _track_sse(
                                            {"type": "token", "content": raw_token}
                                        )
                                        await _flush_assistant_stream_content()
                                elif had_only_text:
                                    raw_token_fallback_chunks += 1

                            elif chunk.get("type") == "reasoning":
                                is_streaming = True
                                reasoning_piece = chunk.get("reasoning") or ""
                                if reasoning_piece:
                                    last_progress_at = loop.time()
                                reasoning_events += 1
                                reasoning_chars += len(reasoning_piece)
                                # Chunk di reasoning possono essere molto frammentati:
                                # interrompiamo solo se supera ENTRAMBI i budget.
                                over_events = (
                                    max_reasoning_events > 0
                                    and reasoning_events > max_reasoning_events
                                )
                                over_chars = (
                                    max_reasoning_chars > 0
                                    and reasoning_chars > max_reasoning_chars
                                )
                                # #region agent log
                                if not reasoning_guard_logged and (
                                    over_events or over_chars
                                ):
                                    reasoning_guard_logged = True
                                    _agent_debug_log(
                                        "H1",
                                        "run_stream:reasoning_guard",
                                        "reasoning_threshold_crossed",
                                        {
                                            "session_id": self.session_id[:12],
                                            "over_events": over_events,
                                            "over_chars": over_chars,
                                            "stop_with_current_and_logic": over_events
                                            and over_chars,
                                            "would_stop_with_or_logic": over_events
                                            or over_chars,
                                            "reasoning_events": reasoning_events,
                                            "max_reasoning_events": max_reasoning_events,
                                            "reasoning_chars": reasoning_chars,
                                            "max_reasoning_chars": max_reasoning_chars,
                                        },
                                    )
                                # #endregion
                                if reasoning_hard_stop and (over_events or over_chars):
                                    stop_event.set()
                                    stop_reason = "reasoning_budget"
                                    msg = (
                                        "Interrotto automaticamente: reasoning loop oltre soglia "
                                        f"(events={reasoning_events}/{max_reasoning_events}, "
                                        f"chars={reasoning_chars}/{max_reasoning_chars})."
                                    )
                                    logger.warning("Hard-stop reasoning guard: %s", msg)
                                    yield _track_sse({"type": "error", "content": msg})
                                    break
                                _chars_gate = (
                                    min_reasoning_chars_without_tool > 0
                                    and reasoning_chars
                                    >= min_reasoning_chars_without_tool
                                )
                                _events_gate = (
                                    max_reasoning_events_without_tool > 0
                                    and reasoning_events
                                    >= max_reasoning_events_without_tool
                                )
                                _no_tool_reasoning_warn = (
                                    tool_calls == 0
                                    and not reasoning_no_tool_warned
                                    and (
                                        _chars_gate
                                        or (
                                            max_reasoning_events_without_tool > 0
                                            and _events_gate
                                            and min_reasoning_chars_without_tool <= 0
                                        )
                                    )
                                )
                                if _no_tool_reasoning_warn:
                                    reasoning_no_tool_warned = True
                                    logger.warning(
                                        "reasoning without tool: chars=%s events=%s tool_calls=0 session=%s",
                                        reasoning_chars,
                                        reasoning_events,
                                        self.session_id[:12],
                                    )
                                    yield _track_sse(
                                        {
                                            "type": "turn_status",
                                            "phase": "reasoning_guard",
                                            "message": (
                                                "Molto reasoning senza tool: esegui la query o un tool "
                                                "rilevante (SQL, memoria, OpenMetadata, …) oppure rispondi."
                                            ),
                                        }
                                    )
                                full_reasoning.append(reasoning_piece)
                                yield _track_sse(chunk)
                                await _flush_assistant_stream_content()
                            elif chunk.get("type") == "stream_end":
                                is_streaming = False
                            elif chunk.get("type") == "tool_event":
                                tool_events += 1
                                last_progress_at = loop.time()
                                if (
                                    max_tool_events > 0
                                    and tool_events > max_tool_events
                                ):
                                    stop_event.set()
                                    msg = (
                                        "Interrotto automaticamente: troppi eventi tool nel turno "
                                        f"({tool_events}/{max_tool_events})."
                                    )
                                    logger.warning(
                                        "Hard-stop tool-event guard: %s", msg
                                    )
                                    yield {"type": "error", "content": msg}
                                    break

                                evt = chunk.get("event") or {}
                                if evt.get("type") == "tool_start":
                                    tool_calls += 1
                                    _tn = str(evt.get("name") or "")
                                    if (
                                        _msg_src == "internal_trigger"
                                        and _tn != "mark_task_completed"
                                    ):
                                        try:
                                            from src.runtime.context import get_context

                                            _mo = get_context().get("mark_once")
                                            if isinstance(_mo, dict) and _mo.get(
                                                "used"
                                            ):
                                                stop_event.set()
                                                stop_reason = "plan_mark_already_used"
                                                _block_msg = (
                                                    "mark_task_completed was already called this turn. "
                                                    "STOP — do not call more tools."
                                                )
                                                yield _track_sse(
                                                    {
                                                        "type": "error",
                                                        "content": _block_msg,
                                                    }
                                                )
                                                break
                                        except Exception:
                                            pass
                                    if plan_controller is not None:
                                        _allowed, _budget_msg = (
                                            plan_controller.on_research_tool_start(_tn)
                                        )
                                        if not _allowed:
                                            yield _track_sse(
                                                plan_controller.sse_phase(
                                                    "research_budget_reached",
                                                    message=_budget_msg,
                                                )
                                            )
                                            yield _track_sse(
                                                {
                                                    "type": "turn_status",
                                                    "phase": "plan_research_budget",
                                                    "tool": _tn,
                                                    "message": _budget_msg or "",
                                                }
                                            )
                                            stop_event.set()
                                            stop_reason = "plan_research_budget"
                                            logger.warning(
                                                "Plan Mode research budget hard-stop session=%s tool=%s",
                                                self.session_id[:8],
                                                _tn,
                                            )
                                            yield _track_sse(
                                                {
                                                    "type": "error",
                                                    "content": _budget_msg or "",
                                                }
                                            )
                                            break
                                    if _tn.startswith("mempalace_"):
                                        yield _track_sse(
                                            {
                                                "type": "turn_status",
                                                "phase": "mempalace",
                                                "tool": _tn,
                                                "message": (
                                                    f"MemPalace · {_tn} "
                                                    f"({tool_calls}/{max_tool_calls or '∞'})"
                                                ),
                                            }
                                        )
                                    # #region agent log
                                    if tool_calls in (1, 3, 5, 8, 12, 16, 20):
                                        _agent_debug_log(
                                            "H3",
                                            "run_stream:tool_start",
                                            "tool_call_milestone",
                                            {
                                                "session_id": self.session_id[:12],
                                                "tool_calls": tool_calls,
                                                "tool_name": str(evt.get("name") or "")[
                                                    :64
                                                ],
                                                "reasoning_chars_so_far": reasoning_chars,
                                                "output_chars_so_far": output_chars,
                                            },
                                        )
                                    # #endregion
                                    if (
                                        max_tool_calls > 0
                                        and tool_calls > max_tool_calls
                                    ):
                                        stop_event.set()
                                        msg = (
                                            "Interrotto automaticamente: troppi tool call nel turno "
                                            f"({tool_calls}/{max_tool_calls})."
                                        )
                                        logger.warning(
                                            "Hard-stop tool-call guard: %s", msg
                                        )
                                        yield {"type": "error", "content": msg}
                                        break
                                    if (
                                        evt.get("name")
                                        == "sandbox_write_workspace_file"
                                    ):
                                        args = evt.get("input", {}) or {}
                                        rp = str(
                                            args.get("relative_path")
                                            or "workspace/file.txt"
                                        )
                                        ct = str(args.get("content") or "")
                                        pending_write_artifacts[rp] = {
                                            "content": ct,
                                            "mode": "write",
                                        }
                                    elif (
                                        evt.get("name") == "sandbox_edit_workspace_file"
                                    ):
                                        args = evt.get("input", {}) or {}
                                        rp = str(
                                            args.get("relative_path")
                                            or "workspace/file.txt"
                                        )
                                        pending_write_artifacts[rp] = {
                                            "old_string": str(
                                                args.get("old_string") or ""
                                            ),
                                            "new_string": str(
                                                args.get("new_string") or ""
                                            ),
                                            "mode": "edit",
                                        }
                                if evt.get("type") == "request_sync":
                                    is_streaming = False
                                    for pe in artifact_parser.flush():
                                        if pe.event == ArtifactEvent.ARTIFACT_END:
                                            if _is_plan_artifact_payload(
                                                pe.artifact_id or "",
                                                pe.artifact_type or "",
                                                pe.content or "",
                                            ):
                                                _pid = _resolve_turn_plan_id(
                                                    plan_controller, pe.artifact_id
                                                )
                                                pending = (
                                                    await _setup_plan_artifact_chunk(
                                                        session_id=self.session_id,
                                                        user_id=self.user_id,
                                                        artifact_id=_pid,
                                                        markdown_content=pe.content
                                                        or "",
                                                    )
                                                )
                                                yield _track_sse(
                                                    {
                                                        "type": "artifact_end",
                                                        "artifact": _plan_artifact_sse_end(
                                                            pe, plan_id=_pid
                                                        ),
                                                    }
                                                )
                                                if pending:
                                                    yield _track_sse(pending)
                                            else:
                                                path, version = artifact_manager.save(
                                                    pe.artifact_id,
                                                    pe.content,
                                                    pe.artifact_type,
                                                    pe.filename,
                                                )
                                                queue_attachment(
                                                    storage_key=str(
                                                        path.relative_to(
                                                            artifact_manager._root
                                                        )
                                                    ),
                                                    original_name=pe.filename
                                                    or pe.artifact_id,
                                                    mime=pe.artifact_type
                                                    or "text/plain",
                                                    size_bytes=len(pe.content or ""),
                                                )
                                                yield _track_sse(
                                                    {
                                                        "type": "artifact_end",
                                                        "artifact": _artifact_end_payload(
                                                            pe, path, version
                                                        ),
                                                    }
                                                )
                                    StreamSync.mark_caught_up(self.session_id)
                                    continue
                                tool_calls_log.append(evt)
                                if evt.get("type") in ("tool_end", "tool_error"):
                                    try:
                                        import src.runtime.db_navigation_mempalace_hooks  # noqa: F401
                                        import src.runtime.exploration_tracker  # noqa: F401
                                        from src.runtime.exploration_tracker import (
                                            record_exploration_tool,
                                        )
                                        from src.runtime.datasource_memory_mode import (
                                            maybe_append_same_turn_reminder,
                                        )

                                        _tool_out = evt.get("output") or evt.get(
                                            "error"
                                        )
                                        record_exploration_tool(
                                            session_id=self.session_id,
                                            tool_name=str(evt.get("name") or ""),
                                            event_type=str(evt.get("type") or ""),
                                            output=_tool_out,
                                            profile_slug=self.profile_name,
                                        )
                                        if evt.get("type") == "tool_end":
                                            _tool_out = maybe_append_same_turn_reminder(
                                                session_id=self.session_id,
                                                profile_slug=self.profile_name,
                                                tool_name=str(evt.get("name") or ""),
                                                event_type="tool_end",
                                                output=_tool_out,
                                            )
                                            evt["output"] = _tool_out
                                        _tenant_qm = (
                                            os.getenv("AION_DEFAULT_TENANT_ID")
                                            or "default"
                                        ).strip() or "default"
                                        await hook_registry.dispatch(
                                            "post_tool",
                                            HookContext(
                                                event="post_tool",
                                                tenant_id=_tenant_qm,
                                                conversation_id=self.session_id,
                                                user_id=self.user_id,
                                                profile=self.profile_name,
                                                payload={
                                                    "event_type": evt.get("type"),
                                                    "tool_name": evt.get("name"),
                                                    "tool_input": evt.get("input"),
                                                    "output": evt.get("output")
                                                    or evt.get("error"),
                                                    "user_input": user_input,
                                                    "sql_query_project": _qm_project,
                                                },
                                            ),
                                        )
                                    except Exception as qm_post_exc:
                                        logger.debug(
                                            "sql_qm post_tool: %s", qm_post_exc
                                        )
                                et = evt.get("type")
                                if isinstance(et, str) and et.startswith(
                                    "orchestration_"
                                ):
                                    yield {k: v for k, v in evt.items()}
                                    if et == "orchestration_plan_pending":
                                        plan_intercepts += 1
                                        if plan_controller is not None:
                                            yield _track_sse(
                                                plan_controller.sse_phase("registered")
                                            )
                                    if single_orch_channel:
                                        continue
                                if (
                                    evt.get("type") == "tool_end"
                                    and evt.get("name")
                                    == "sandbox_write_workspace_file"
                                ):
                                    output_text = str(evt.get("output") or "")
                                    saved_path = ""
                                    if "workspace/" in output_text:
                                        saved_path = output_text.split("workspace/", 1)[
                                            1
                                        ].strip()
                                        saved_path = "workspace/" + saved_path.split()[
                                            0
                                        ].strip("`\"'.,)")
                                    if not saved_path:
                                        saved_path = "workspace/file.txt"
                                    data = pending_write_artifacts.pop(
                                        saved_path, {"content": "", "mode": "write"}
                                    )
                                    ct = data.get("content") or ""
                                    aid = saved_path.replace("/", "_").replace(".", "_")
                                    a_type = (
                                        "html"
                                        if saved_path.endswith(".html")
                                        else "python"
                                        if saved_path.endswith(".py")
                                        else "text"
                                    )
                                    yield _track_sse(
                                        {
                                            "type": "artifact_start",
                                            "artifact": {
                                                "identifier": aid,
                                                "type": a_type,
                                                "title": f"📄 Artifact: {saved_path}",
                                                "auto_execute": False,
                                            },
                                        }
                                    )
                                    yield _track_sse(
                                        {
                                            "type": "artifact_content",
                                            "content": ct,
                                            "artifact_id": aid,
                                        }
                                    )
                                    yield _track_sse(
                                        {
                                            "type": "artifact_end",
                                            "artifact": {
                                                "identifier": aid,
                                                "type": a_type,
                                                "title": f"📄 Artifact: {saved_path}",
                                                "path": saved_path,
                                                "saved": True,
                                                "version": 1,
                                            },
                                        }
                                    )
                                    queue_attachment(
                                        storage_key=saved_path,
                                        original_name=Path(saved_path).name,
                                        mime=a_type,
                                        size_bytes=len(ct),
                                    )
                                elif (
                                    evt.get("type") == "tool_end"
                                    and evt.get("name") == "mark_task_completed"
                                    and _msg_src == "internal_trigger"
                                ):
                                    stop_event.set()
                                    stop_reason = "plan_task_completed"
                                    outcome: Dict[str, Any] = {
                                        "type": "turn_outcome",
                                        "code": "plan_task_completed",
                                        "message": (
                                            "Task marked completed. Turn interrupted — "
                                            "the server will continue with the next task."
                                        ),
                                    }
                                    yield _track_sse(outcome)
                                elif (
                                    evt.get("type") == "tool_end"
                                    and evt.get("name") == "sandbox_edit_workspace_file"
                                ):
                                    output_text = str(evt.get("output") or "")
                                    saved_path = ""
                                    try:
                                        out_data = json.loads(output_text)
                                        if isinstance(out_data, dict):
                                            saved_path = str(out_data.get("file") or "")
                                    except Exception:
                                        pass
                                    if not saved_path:
                                        saved_path = "workspace/file.txt"
                                    data = pending_write_artifacts.pop(saved_path, {})
                                    if data.get("mode") == "edit":
                                        try:
                                            from src.session_workspace import (
                                                safe_resolve,
                                            )

                                            p = safe_resolve(
                                                self.session_id,
                                                saved_path,
                                                must_exist=True,
                                            )
                                            updated_content = p.read_text(
                                                encoding="utf-8", errors="replace"
                                            )
                                        except Exception:
                                            updated_content = (
                                                f"[file aggiornato: {saved_path}]"
                                            )

                                        aid = (
                                            saved_path.replace("/", "_").replace(
                                                ".", "_"
                                            )
                                            + "_edit"
                                        )
                                        a_type = (
                                            "python"
                                            if saved_path.endswith(".py")
                                            else "html"
                                            if saved_path.endswith(".html")
                                            else "text"
                                        )
                                        yield _track_sse(
                                            {
                                                "type": "artifact_start",
                                                "artifact": {
                                                    "identifier": aid,
                                                    "type": a_type,
                                                    "title": f"✏️ Edit: {saved_path}",
                                                    "auto_execute": False,
                                                },
                                            }
                                        )
                                        yield _track_sse(
                                            {
                                                "type": "artifact_content",
                                                "content": updated_content,
                                                "artifact_id": aid,
                                            }
                                        )
                                        yield _track_sse(
                                            {
                                                "type": "artifact_end",
                                                "artifact": {
                                                    "identifier": aid,
                                                    "type": a_type,
                                                    "title": f"✏️ Edit: {saved_path}",
                                                    "path": saved_path,
                                                    "saved": True,
                                                    "version": 1,
                                                },
                                            }
                                        )
                                        queue_attachment(
                                            storage_key=saved_path,
                                            original_name=Path(saved_path).name,
                                            mime=a_type,
                                            size_bytes=len(updated_content),
                                        )

                                if evt.get("type") == "tool_start":
                                    queue_tool_step(evt, is_start=True)
                                    if assistant_message_id:
                                        await persist_pending_turn_records(
                                            assistant_message_id,
                                            only_new=True,
                                            include_attachments=False,
                                        )
                                elif evt.get("type") == "tool_end":
                                    try:
                                        call_id = str(evt.get("id") or "").strip()
                                        out_tokens = count_tokens(
                                            str(evt.get("output") or "")
                                        )
                                        inp_tokens = 0
                                        for ps in pending_db_steps:
                                            if ps.get("step_id") == call_id:
                                                inp_tokens = count_tokens(
                                                    ps.get("input") or ""
                                                )
                                                break
                                        evt["tokens_in"] = inp_tokens
                                        evt["tokens_out"] = out_tokens
                                    except Exception as e:
                                        logger.warning(
                                            "Failed to count tool tokens: %s", e
                                        )
                                    queue_tool_step(evt)
                                    if assistant_message_id:
                                        await persist_pending_turn_records(
                                            assistant_message_id,
                                            only_new=True,
                                            include_attachments=False,
                                        )
                                elif evt.get("type") == "tool_error":
                                    queue_tool_step(evt, is_error=True)
                                    if assistant_message_id:
                                        await persist_pending_turn_records(
                                            assistant_message_id,
                                            only_new=True,
                                            include_attachments=False,
                                        )

                                yield _track_sse(chunk)

                drain_sec = float(os.getenv("AION_AGENT_DRAIN_TIMEOUT_SEC", "0"))
                if stop_event.is_set() and stop_reason != "completed" and drain_sec > 0:
                    try:
                        turn_result = await asyncio.wait_for(
                            agent_task, timeout=drain_sec
                        )
                    except asyncio.TimeoutError:
                        logger.error(
                            "agent_task drain timeout after stop_reason=%s session=%s "
                            "(thread may still run MCP tools; consider new chat or raise "
                            "AION_TOOL_CALLS_MAX_PER_TURN for bulk MemPalace import)",
                            stop_reason,
                            self.session_id[:12],
                        )
                        agent_task.cancel()
                        turn_result = None
                        yield _track_sse(
                            {
                                "type": "turn_outcome",
                                "code": f"agent_drain_timeout_{stop_reason}",
                                "message": (
                                    f"The turn was interrupted ({stop_reason}) but the agent "
                                    f"did not finish within {int(drain_sec)}s (probabili tool MCP "
                                    "ancora in esecuzione). Apri una nuova chat o usa lo script "
                                    "`scripts/bootstrap_db_navigation_mempalace.py` per import bulk."
                                ),
                            }
                        )
                else:
                    turn_result = await agent_task
                _agent_debug_log(
                    "H1",
                    "run_stream:turn_result",
                    "agent_task_finished",
                    {
                        "session_id": self.session_id[:12],
                        "turn_result_type": type(turn_result).__name__,
                        "turn_result_is_none": turn_result is None,
                        "full_response_len": len("".join(full_response)),
                        "stop_reason": stop_reason,
                    },
                )
                logger.info(
                    ">>> [DEBUG] Agent turn finished. Result type: %s",
                    type(turn_result),
                )
                # Supporto sia per liste che per dict (Pipeline result)
                new_messages = []
                raw_list = []
                if isinstance(turn_result, list):
                    raw_list = turn_result
                elif isinstance(turn_result, dict):
                    # Estraiamo i messaggi dal dizionario dei risultati
                    for key in ["messages", "replies", "answer"]:
                        if key in turn_result and isinstance(turn_result[key], list):
                            raw_list = turn_result[key]
                            break
                    if not raw_list:
                        # Fallback: cerca una lista di ChatMessage in qualsiasi chiave
                        for val in turn_result.values():
                            if (
                                isinstance(val, list)
                                and len(val) > 0
                                and hasattr(val[0], "role")
                            ):
                                raw_list = val
                                break

                # Applica il matching dell'indice dell'ultimo messaggio di input per ottenere solo i messaggi nuovi
                if raw_list and messages:
                    idx = _find_input_end_index(messages, raw_list)
                    if idx >= 0:
                        new_messages = raw_list[idx + 1 :]
                    else:
                        # Fallback di sicurezza basato sulla lunghezza se non troviamo il messaggio di input
                        new_messages = raw_list[len(messages) :]
                else:
                    new_messages = raw_list

                turn_new_messages = list(new_messages) if new_messages else []

                if new_messages:
                    for i, msg in enumerate(new_messages):
                        content = chat_message_text(msg)
                        raw_role = (
                            msg.role.value
                            if hasattr(msg.role, "value")
                            else str(msg.role)
                        )
                        role = normalize_message_role(raw_role)
                        # Recupero ragionamento da metadati o da accumulo streaming
                        reasoning = msg.meta.get("reasoning") or msg.meta.get(
                            "reasoning_content"
                        )
                        if (
                            not reasoning
                            and role == "assistant"
                            and not msg.tool_calls
                            and i == (len(new_messages) - 1)
                        ):
                            reasoning = "".join(full_reasoning)
                        tool_call_id = None
                        tool_name = None

                        if role == "assistant" and msg.tool_calls:
                            tool_name = msg.tool_calls[0].tool_name
                            tool_call_id = msg.tool_calls[0].id
                        elif role == "tool":
                            tool_name = msg.meta.get("tool_name")
                            tool_call_id = msg.meta.get("tool_call_id")

                        # Se è l'ultimo messaggio assistant del turno, usiamo l'assistant_message_id sincronizzato
                        mid = None
                        if (
                            role == "assistant"
                            and not msg.tool_calls
                            and i == (len(new_messages) - 1)
                        ):
                            mid = assistant_message_id
                            logger.debug(
                                "Assigning synchronized ID %s to final assistant message",
                                mid,
                            )

                        try:
                            tl_json = (
                                timeline_builder.to_json()
                                if mid == assistant_message_id and role == "assistant"
                                else None
                            )
                            persist_content = content
                            if mid == assistant_message_id and role == "assistant":
                                streamed = "".join(full_response).strip()
                                if streamed and not (persist_content or "").strip():
                                    persist_content = streamed
                            if mid:
                                await history_manager.upsert_message_content(
                                    self.session_id,
                                    mid,
                                    role,
                                    persist_content,
                                    profile_name=self.profile_name,
                                    user_id=self.user_id,
                                    tool_name=tool_name,
                                    tool_call_id=tool_call_id,
                                    reasoning=reasoning,
                                    timeline_json=tl_json,
                                    metadata_json=_plan_meta_json
                                    if mid == user_message_id
                                    or mid == assistant_message_id
                                    else None,
                                )
                                if mid == assistant_message_id and role == "assistant":
                                    assistant_message_persisted = True
                            else:
                                await history_manager.add_message(
                                    self.session_id,
                                    role,
                                    content,
                                    profile_name=self.profile_name,
                                    user_id=self.user_id,
                                    tool_name=tool_name,
                                    tool_call_id=tool_call_id,
                                    reasoning=reasoning,
                                    message_id=None,
                                    timeline_json=tl_json,
                                )
                            logger.info(
                                ">>> [DEBUG] Persisted message: role=%s, id=%s",
                                role,
                                mid,
                            )
                        except Exception as p_err:
                            logger.error("Persistence error: %s", p_err)
                else:
                    logger.warning(
                        "turn_result has no new messages: %s", type(turn_result)
                    )

            except asyncio.TimeoutError:
                _turn_status = "timeout"
                _turn_error_type = "TimeoutError"
                logger.error("Turn timeout for session %s", self.session_id)
                yield {"type": "error", "content": "Operation timed out."}
            except asyncio.CancelledError:
                _turn_status = "cancelled"
                _turn_error_type = "CancelledError"
                stop_event.set()
                raise
            except Exception as e:
                _turn_status = "error"
                _turn_error_type = type(e).__name__
                logger.error(">>> [FATAL] Error in run_stream: %s", e, exc_info=True)
                yield {"type": "error", "content": str(e)}
            finally:
                try:
                    from src.runtime.sql_query_memory_context import (
                        clear_sql_qm_turn_context,
                    )

                    clear_sql_qm_turn_context(self.session_id)
                except Exception:
                    pass
                logger.info(
                    "turn_metrics session=%s stop_reason=%s stream_events=%s control_events=%s "
                    "output_events=%s output_chars=%s reasoning_chars=%s tool_calls=%s tool_events=%s "
                    "artifact_parse_hits=%s artifact_salvage=%s plan_intercepts=%s raw_token_fallback_chunks=%s",
                    self.session_id,
                    stop_reason,
                    stream_events,
                    control_events,
                    output_events,
                    output_chars,
                    reasoning_chars,
                    tool_calls,
                    tool_events,
                    artifact_parse_hits,
                    artifact_salvage,
                    plan_intercepts,
                    raw_token_fallback_chunks,
                )
                # #region agent log
                _llm_steps = _llm_steps_done
                _agent_debug_log(
                    "H5",
                    "run_stream:finally",
                    "turn_metrics",
                    {
                        "session_id": self.session_id[:12],
                        "stop_reason": stop_reason,
                        "llm_steps": _llm_steps,
                        "max_agent_steps": getattr(self.agent, "max_agent_steps", None),
                        "stream_events": stream_events,
                        "output_chars": output_chars,
                        "reasoning_chars": reasoning_chars,
                        "reasoning_events": reasoning_events,
                        "tool_calls": tool_calls,
                        "tool_events": tool_events,
                        "full_response_len": len("".join(full_response)),
                    },
                )
                # #endregion
                skip_plan_guard = _skip_plan_turn

                # Final parser flush to avoid losing trailing/truncated `<plan>` blocks.
                try:
                    for pe in artifact_parser.flush():
                        if pe.event == ArtifactEvent.TEXT:
                            full_response.append(pe.content)
                            yield _track_sse({"type": "token", "content": pe.content})
                        elif pe.event == ArtifactEvent.ARTIFACT_START:
                            yield _track_sse(
                                {
                                    "type": "artifact_start",
                                    "artifact": {
                                        "identifier": pe.artifact_id,
                                        "type": pe.artifact_type,
                                        "title": pe.artifact_title,
                                        "auto_execute": pe.auto_execute,
                                    },
                                }
                            )
                        elif pe.event == ArtifactEvent.ARTIFACT_CONTENT:
                            yield _track_sse(
                                {
                                    "type": "artifact_content",
                                    "content": pe.content,
                                    "artifact_id": pe.artifact_id,
                                }
                            )
                        elif pe.event == ArtifactEvent.ARTIFACT_END:
                            if _is_plan_artifact_payload(
                                pe.artifact_id or "",
                                pe.artifact_type or "",
                                pe.content or "",
                            ):
                                _pid = _resolve_turn_plan_id(
                                    plan_controller, pe.artifact_id
                                )
                                pending = await _setup_plan_artifact_chunk(
                                    session_id=self.session_id,
                                    user_id=self.user_id,
                                    artifact_id=_pid,
                                    markdown_content=pe.content or "",
                                )
                                yield _track_sse(
                                    {
                                        "type": "artifact_end",
                                        "artifact": _plan_artifact_sse_end(
                                            pe, plan_id=_pid
                                        ),
                                    }
                                )
                                if pending:
                                    yield _track_sse(pending)
                            else:
                                path, version = artifact_manager.save(
                                    pe.artifact_id,
                                    pe.content,
                                    pe.artifact_type,
                                    pe.filename,
                                )
                                queue_attachment(
                                    storage_key=str(
                                        path.relative_to(artifact_manager._root)
                                    ),
                                    original_name=pe.filename or pe.artifact_id,
                                    mime=pe.artifact_type or "text/plain",
                                    size_bytes=len(pe.content or ""),
                                )
                                yield _track_sse(
                                    {
                                        "type": "artifact_end",
                                        "artifact": _artifact_end_payload(
                                            pe, path, version
                                        ),
                                    }
                                )
                except Exception as flush_err:
                    logger.warning("Artifact parser flush failed: %s", flush_err)

                # Plan Mode: text-parser finalization (legacy; skipped when tool-first is primary).
                if (
                    effective_agent_mode == "plan"
                    and not skip_plan_guard
                    and plan_intercepts == 0
                    and plan_text_parser_enabled()
                ):
                    try:
                        from src.runtime.plan_engine import (
                            PLAN_FINALIZE_USER_MESSAGE,
                            PlanFinalizer,
                        )

                        if plan_controller is not None:
                            yield _track_sse(
                                plan_controller.sse_phase(
                                    "finalizing",
                                    message="Structuring the execution plan…",
                                )
                            )
                        _turn_pid = _resolve_turn_plan_id(plan_controller, None)
                        _finalize = await PlanFinalizer.finalize(
                            "".join(full_response),
                            user_message=user_input or "",
                            plan_id=_turn_pid,
                        )
                        if _finalize is not None:
                            plan_finalize_source = _finalize.source
                            pid = _finalize.plan_id or _turn_pid
                            pending = await _setup_plan_artifact_chunk(
                                session_id=self.session_id,
                                user_id=self.user_id,
                                artifact_id=pid,
                                markdown_content=_finalize.markdown,
                            )
                            if pending:
                                yield _track_sse(pending)
                                plan_intercepts = 1
                                if _finalize.source and _finalize.source != "tool":
                                    plan_text_fallback_count = 1
                                if plan_controller is not None:
                                    yield _track_sse(
                                        plan_controller.sse_progress(
                                            _finalize.markdown,
                                            tasks_count=_finalize.tasks_count,
                                            revision=1,
                                        )
                                    )
                                    yield _track_sse(
                                        plan_controller.sse_phase("registered")
                                    )
                                logger.info(
                                    "Plan Mode finalize: source=%s tasks=%s plan_id=%s session=%s",
                                    _finalize.source,
                                    _finalize.tasks_count,
                                    pid,
                                    self.session_id[:8],
                                )
                        else:
                            plan_finalize_source = "failed"
                            if plan_controller is not None:
                                yield _track_sse(
                                    plan_controller.sse_plan_error(
                                        PLAN_FINALIZE_USER_MESSAGE
                                    )
                                )
                            yield _track_sse(
                                {"type": "token", "content": PLAN_FINALIZE_USER_MESSAGE}
                            )
                            logger.info(
                                "Plan Mode finalize: no valid plan (plan_id=%s session=%s)",
                                _turn_pid,
                                self.session_id[:8],
                            )
                    except Exception as finalize_exc:
                        logger.warning("Plan Mode finalize failed: %s", finalize_exc)
                        if plan_controller is not None:
                            yield _track_sse(
                                plan_controller.sse_phase(
                                    "error",
                                    message=str(finalize_exc)[:200],
                                )
                            )

                if effective_agent_mode == "plan" and not skip_plan_guard:
                    try:
                        from src.runtime.plan_mode import plan_mode_tool_first
                        from src.runtime.plan_mode_guard import plan_mode_response_valid

                        full_plan_text = "".join(full_response)
                        ok, reason = plan_mode_response_valid(
                            full_plan_text,
                            plan_registered=plan_intercepts > 0,
                            tool_first=plan_mode_tool_first(),
                        )
                        if not ok:
                            logger.warning(
                                "plan_mode_invalid_response session=%s reason=%s plan_intercepts=%s",
                                self.session_id[:8],
                                reason,
                                plan_intercepts,
                            )
                            yield {
                                "type": "error",
                                "content": (
                                    "Plan Mode: deliverable content leaked in chat "
                                    f"({reason}). Use draft_execution_plan and keep chat to a short summary."
                                ),
                            }
                    except Exception as guard_exc:
                        logger.debug("plan_mode_guard skipped: %s", guard_exc)

                if artifact_parse_hits == 0:
                    try:
                        from src.runtime.artifact_coercion import (
                            salvage_artifact_from_response,
                        )

                        _salvaged = salvage_artifact_from_response(
                            "".join(full_response)
                        )
                        if _salvaged and not _is_plan_artifact_payload(
                            _salvaged.artifact_id,
                            _salvaged.artifact_type,
                            _salvaged.content,
                        ):
                            path, version = artifact_manager.save(
                                _salvaged.artifact_id,
                                _salvaged.content,
                                _salvaged.artifact_type,
                                _salvaged.filename,
                            )
                            artifact_salvage = 1
                            yield _track_sse(
                                {
                                    "type": "artifact_start",
                                    "artifact": {
                                        "identifier": _salvaged.artifact_id,
                                        "type": _salvaged.artifact_type,
                                        "title": _salvaged.title,
                                        "auto_execute": False,
                                    },
                                }
                            )
                            yield _track_sse(
                                {
                                    "type": "artifact_content",
                                    "content": _salvaged.content,
                                    "artifact_id": _salvaged.artifact_id,
                                }
                            )
                            queue_attachment(
                                storage_key=str(
                                    path.relative_to(artifact_manager._root)
                                ),
                                original_name=_salvaged.filename
                                or _salvaged.artifact_id,
                                mime=_salvaged.artifact_type or "text/markdown",
                                size_bytes=len(_salvaged.content or ""),
                            )
                            yield _track_sse(
                                {
                                    "type": "artifact_end",
                                    "artifact": {
                                        "identifier": _salvaged.artifact_id,
                                        "type": _salvaged.artifact_type,
                                        "title": _salvaged.title,
                                        "path": str(
                                            path.relative_to(artifact_manager._root)
                                        ),
                                        "version": version,
                                        "saved": True,
                                    },
                                }
                            )
                            logger.warning(
                                "Artifact salvage: recovered %s (session=%s)",
                                _salvaged.artifact_id,
                                self.session_id[:8],
                            )
                    except Exception as salvage_exc:
                        logger.warning("Artifact salvage failed: %s", salvage_exc)

                await _flush_assistant_stream_content(force=True)
                if keepalive_task is not None and not keepalive_task.done():
                    keepalive_task.cancel()
                if "agent_task" in locals() and not agent_task.done():
                    agent_task.cancel()
                if "tool_listener_task" in locals():
                    tool_listener_task.cancel()
                StreamSync.purge(self.session_id)

                if prompt_debug_enabled():
                    try:
                        from src.runtime.plan_coercion import (
                            coerce_chat_plan_to_canonical_markdown,
                            looks_like_chat_plan,
                        )
                        from src.runtime.prompt_snapshot import (
                            patch_prompt_snapshot_output,
                        )

                        _raw_assistant = "".join(full_response)
                        _coerced_md = None
                        if effective_agent_mode == "plan" and looks_like_chat_plan(
                            _raw_assistant
                        ):
                            _coerced_md = coerce_chat_plan_to_canonical_markdown(
                                _raw_assistant
                            )
                        _patched = patch_prompt_snapshot_output(
                            self.session_id,
                            assistant_message_id,
                            assistant_output=_raw_assistant,
                            plan_coerced_markdown=_coerced_md,
                            plan_intercepts=plan_intercepts,
                            plan_finalize_source=plan_finalize_source,
                            plan_text_fallback_count=plan_text_fallback_count,
                            artifact_parse_hits=artifact_parse_hits,
                            artifact_salvage=artifact_salvage,
                            raw_token_fallback_chunks=raw_token_fallback_chunks,
                        )
                        if _patched:
                            yield _track_sse(
                                {
                                    "type": "prompt_snapshot",
                                    "assistant_message_id": assistant_message_id,
                                    "snapshot": _patched,
                                }
                            )
                    except Exception as snap_exc:
                        logger.debug(
                            "prompt snapshot post-run patch failed: %s", snap_exc
                        )

                final_text = "".join(full_response).strip()
                if not final_text:
                    for seg in timeline_builder.to_list() or []:
                        if seg.get("kind") == "text":
                            final_text += str(seg.get("content") or "")
                    final_text = final_text.strip()
                try:
                    from src.runtime.turn.post_turn import finalize_turn_outcome

                    final_text, _outcome_chunk = await finalize_turn_outcome(
                        session_id=self.session_id,
                        profile_name=self.profile_name,
                        stop_reason=stop_reason,
                        final_text=final_text,
                        full_reasoning="".join(full_reasoning),
                        tool_calls=tool_calls,
                        tool_events=tool_events,
                        turn_new_messages=turn_new_messages,
                        turn_context_stats=turn_context_stats,
                        agent=self.agent,
                        pending_db_steps=pending_db_steps,
                        timeline_builder=timeline_builder,
                        plan_intercepts=plan_intercepts,
                    )
                    if _outcome_chunk:
                        if (
                            _outcome_chunk.get("message")
                            and not "".join(full_response).strip()
                        ):
                            yield _track_sse(
                                {"type": "token", "content": _outcome_chunk["message"]}
                            )
                        yield _track_sse(_outcome_chunk)
                    elif final_text and not "".join(full_response).strip():
                        yield _track_sse({"type": "token", "content": final_text})
                except Exception as post_turn_exc:
                    logger.debug("finalize_turn_outcome failed: %s", post_turn_exc)
                tl_json = timeline_builder.to_json()
                if assistant_message_id:
                    try:
                        await history_manager.upsert_message_content(
                            self.session_id,
                            assistant_message_id,
                            "assistant",
                            final_text,
                            profile_name=self.profile_name,
                            user_id=self.user_id,
                            reasoning="".join(full_reasoning) or None,
                            timeline_json=tl_json,
                            metadata_json=_plan_meta_json,
                        )
                        assistant_message_persisted = True
                    except Exception as db_err:
                        logger.warning(
                            "Failed to persist final assistant message: %s", db_err
                        )
                if pending_db_steps or pending_db_attachments:
                    await persist_pending_turn_records(
                        assistant_message_id if assistant_message_persisted else None
                    )
                try:
                    loop.create_task(
                        ltm_orchestrator.extract_and_persist(
                            self.session_id,
                            self.user_id,
                            user_input,
                            final_text,
                            mode="turn",
                            active_project=_qm_project,
                            profile_slug=self.profile_name,
                        )
                    )
                    try:
                        from .learning.skill_distiller import skill_distiller

                        loop.create_task(
                            skill_distiller.maybe_distill(
                                self.session_id,
                                self.profile_name,
                                user_input,
                                final_text,
                                tool_calls_log,
                            )
                        )
                    except Exception:
                        pass
                except Exception as post_err:
                    logger.error("Failed post-turn tasks: %s", post_err)

            # Calculate duration
            _turn_duration = time.monotonic() - _turn_start_time

            # Estimate prompt tokens
            if _accumulated_prompt_tokens > 0:
                _prompt_tokens_est = _accumulated_prompt_tokens
            else:
                try:
                    _prompt_stats = estimate_full_prompt_tokens(self.agent, messages)
                    _prompt_tokens_est = _prompt_stats.get("total", 0)
                except Exception as est_err:
                    logger.debug("Failed to estimate prompt tokens: %s", est_err)
                    _prompt_tokens_est = 0

            # Compute completion and reasoning tokens
            if _accumulated_completion_tokens > 0:
                _completion_tokens_est = _accumulated_completion_tokens
            else:
                _completion_text = final_text or ""
                _completion_tokens_est = count_tokens(_completion_text)

            if _accumulated_reasoning_tokens > 0:
                _reasoning_tokens_est = _accumulated_reasoning_tokens
            else:
                _reasoning_text = "".join(full_reasoning)
                _reasoning_tokens_est = count_tokens(_reasoning_text)

            _post_turn_payload = {
                "duration": _turn_duration,
                "status": _turn_status,
                "error_type": _turn_error_type,
                "model": os.getenv("AION_MODEL", "AIONQ35-35-Q8B"),
                "prompt_tokens": _prompt_tokens_est,
                "completion_tokens": _completion_tokens_est,
                "reasoning_tokens": _reasoning_tokens_est,
                "llm_calls": _llm_steps_done,
            }

            await hook_registry.dispatch(
                "post_turn",
                HookContext(
                    event="post_turn",
                    tenant_id="default",
                    conversation_id=self.session_id,
                    user_id=self.user_id,
                    profile=self.profile_name,
                    payload=_post_turn_payload,
                ),
            )
            _agent_debug_log(
                "H4",
                "run_stream:final",
                "yielding_final",
                {
                    "session_id": self.session_id[:12],
                    "final_text_len": len(final_text),
                    "stop_reason": stop_reason,
                    "assistant_persisted": assistant_message_persisted,
                },
            )
            yield _track_sse({"type": "final", "text": final_text})

        except Exception as e:
            logger.error(
                ">>> [CRITICAL] Outer run_stream failure: %s", e, exc_info=True
            )
            yield {"type": "error", "content": str(e)}
        finally:
            await redis_clear_stream_active(self.session_id)
            reset_web_search_request_context(_web_tok)
            if span:
                try:
                    from opentelemetry import context

                    if otel_token:
                        context.detach(otel_token)
                    span.end()
                except Exception as e:
                    logger.warning("Errore chiusura span OTel: %s", e)

    async def run(self, user_input: str) -> Dict[str, Any]:
        async for chunk in self.run_stream(user_input):
            if chunk["type"] == "final":
                return {
                    "text": chunk["text"],
                    "charts": chunk.get("charts", []),
                    "success": True,
                }
        return {"text": "", "charts": [], "success": False}
