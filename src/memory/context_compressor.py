"""Compressione contesto (stile Claude compaction): transcript intero, tool/timeline, budget API."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from haystack.dataclasses import ChatMessage

from ..haystack_chat import chat_message_text
from .llm_extract import complete_text_sync

logger = logging.getLogger("aion.memory.compressor")

COMPACTION_MARKER = "[AION COMPACTION — contesto precedente sintetizzato]"
CONTEXT_SUMMARY_MARKER = "[CONTEXT SUMMARY"

try:
    import tiktoken

    _enc = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_enc.encode(text or ""))
except ImportError:

    def count_tokens(text: str) -> int:
        return max(1, len(text or "") // 4)


def _env_bool(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def model_context_window() -> int:
    raw = (
        os.getenv("AION_MODEL_MAX_CONTEXT")
        or os.getenv("AION_CONTEXT_COMPRESS_MODEL_WINDOW")
        or "131072"
    )
    try:
        return max(4096, int(raw))
    except ValueError:
        return 131072


def reserve_output_tokens() -> int:
    if _env_bool("AION_CONTEXT_COMPRESS_RESERVE_OUTPUT", "1"):
        try:
            return max(256, int(os.getenv("AION_CHAT_MAX_TOKENS", "8192")))
        except ValueError:
            return 8192
    try:
        return max(
            0, int(os.getenv("AION_CONTEXT_COMPRESS_RESERVE_OUTPUT_TOKENS", "0"))
        )
    except ValueError:
        return 0


def overhead_floor_tokens() -> int:
    try:
        return max(0, int(os.getenv("AION_CONTEXT_COMPRESS_FIXED_OVERHEAD", "4096")))
    except ValueError:
        return 4096


@dataclass(frozen=True)
class CompactionTranscriptRow:
    role: str
    content: str
    timeline_json: Optional[str] = None
    reasoning: Optional[str] = None
    tool_name: Optional[str] = None


def timeline_json_to_transcript(
    timeline_json: Optional[str], *, max_tool_out: int = 1200
) -> str:
    if not timeline_json or not str(timeline_json).strip():
        return ""
    try:
        parsed = json.loads(timeline_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    segments: List[Dict[str, Any]]
    if isinstance(parsed, list):
        segments = [s for s in parsed if isinstance(s, dict)]
    elif isinstance(parsed, dict):
        raw = parsed.get("segments")
        segments = (
            [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []
        )
    else:
        return ""
    lines: List[str] = []
    for seg in segments:
        kind = str(seg.get("kind") or "")
        if kind == "tool":
            name = str(seg.get("name") or "tool")
            status = str(seg.get("status") or "")
            inp = seg.get("input")
            out = seg.get("output") or seg.get("error")
            inp_s = json.dumps(inp, ensure_ascii=False)[:600] if inp is not None else ""
            out_s = ""
            if out is not None:
                out_s = json.dumps(out, ensure_ascii=False)[:max_tool_out]
            lines.append(f"    [tool {name} {status}] input={inp_s} output={out_s}")
        elif kind == "reasoning":
            piece = str(seg.get("content") or "")[:800]
            if piece.strip():
                lines.append(f"    [reasoning] {piece}")
        elif kind == "text":
            piece = str(seg.get("content") or "")[:400]
            if piece.strip():
                lines.append(f"    [assistant-text] {piece}")
    return "\n".join(lines)


def build_transcript_from_rows(rows: Sequence[CompactionTranscriptRow]) -> str:
    parts: List[str] = []
    for row in rows:
        role = (row.role or "user").strip()
        body = (row.content or "").strip()
        if COMPACTION_MARKER in body or CONTEXT_SUMMARY_MARKER in body:
            continue
        if row.tool_name:
            parts.append(f"{role} [tool={row.tool_name}]: {body[:2000]}")
        else:
            parts.append(f"{role}: {body[:3000]}")
        if row.reasoning and str(row.reasoning).strip():
            parts.append(f"  reasoning: {str(row.reasoning)[:1200]}")
        tl = timeline_json_to_transcript(row.timeline_json)
        if tl:
            parts.append(tl)
    return "\n".join(parts)


def format_compaction_block(summary_text: str, *, source_messages: int = 0) -> str:
    head = COMPACTION_MARKER
    if source_messages > 0:
        head += f" ({source_messages} turni precedenti)"
    return f"{head}\n{summary_text.strip()}"


def compaction_summary_prompt(lang: str | None = None) -> str:
    from src.runtime.user_language import default_ui_language, normalize_ui_language

    lang_lower = normalize_ui_language(lang) or default_ui_language()
    if lang_lower == "en":
        return (
            "You are a context compressor for AI agents (Claude compaction style). "
            "Synthesize the entire previous conversation into a high-fidelity summary. "
            "You must include: user goals, decisions made, numeric facts, "
            "file/server/metric names, tool call outcomes (success/error and key data), "
            "resolved or open errors, explicit user constraints. "
            "Do not invent. Respond in English, compact markdown with short sections."
        )
    elif lang_lower == "es":
        return (
            "Eres un compresor de contexto para agentes de IA (estilo Claude compaction). "
            "Sintetiza toda la conversación anterior en un resumen de alta fidelidad. "
            "Debes incluir: objetivos del usuario, decisiones tomadas, hechos numéricos, "
            "nombres de archivos/servidores/métricas, resultados de llamadas a herramientas (éxito/error y datos clave), "
            "errores resueltos o abiertos, restricciones explícitas del usuario. "
            "No inventes. Responde en español, markdown compacto con secciones cortas."
        )
    elif lang_lower == "fr":
        return (
            "Vous êtes un compresseur de contexte pour agents IA (style Claude compaction). "
            "Synthétisez toute la conversation précédente en un résumé haute fidélité. "
            "Vous devez inclure : objectifs de l'utilisateur, décisions prises, faits numériques, "
            "noms de fichiers/serveurs/métriques, résultats des appels d'outils (succès/erreur et données clés), "
            "erreurs résolues ou ouvertes, contraintes explicites de l'utilisateur. "
            "N'inventez rien. Répondez en français, markdown compact avec des sections courtes."
        )
    elif lang_lower == "de":
        return (
            "Sie sind ein Kontext-Kompressor für KI-Agenten (Claude-Kompaktierungsstil). "
            "Synthetisieren Sie die gesamte vorherige Konversation in eine detailgetreue Zusammenfassung. "
            "Sie müssen Folgendes angeben: Benutzerziele, getroffene Entscheidungen, numerische Fakten, "
            "Datei-/Server-/Metriknamen, Ergebnisse von Tool-Aufrufen (Erfolg/Fehler und Schlüsseldaten), "
            "gelöste oder offene Fehler, explizite Benutzereinschränkungen. "
            "Erfinden Sie nichts. Antworten Sie auf Deutsch, kompaktes Markdown mit kurzen Abschnitten."
        )
    else:
        return (
            "Sei un compressore di contesto per agenti AI (stile Claude compaction). "
            "Sintetizza l'intera conversazione precedente in un riepilogo ad alta fedeltà. "
            "Includi obbligatoriamente: obiettivi dell'utente, decisioni prese, fatti numerici, "
            "nomi file/server/metriche, esiti delle chiamate tool (successo/errore e dati chiave), "
            "errori risolti o ancora aperti, vincoli espliciti dell'utente. "
            "Non inventare. Rispondi in italiano, markdown compatto con sezioni brevi."
        )


class ContextCompressor:
    def __init__(
        self,
        window_size: Optional[int] = None,
        threshold: float = 0.5,
        keep_last: int = 6,
        reserve_output: Optional[int] = None,
    ):
        self.window_size = (
            window_size if window_size is not None else model_context_window()
        )
        self.threshold = threshold
        self.keep_last = keep_last
        self.reserve_output_tokens = (
            reserve_output if reserve_output is not None else reserve_output_tokens()
        )

    def total_tokens(self, messages: List[ChatMessage]) -> int:
        return sum(count_tokens(chat_message_text(m)) for m in messages)

    def compress_trigger_tokens(self) -> int:
        return max(1024, int(self.window_size * self.threshold))

    def max_prompt_tokens(self) -> int:
        return max(2048, self.window_size - self.reserve_output_tokens)

    def max_input_tokens(self, fixed_overhead: int = 0) -> int:
        return self.max_prompt_tokens()

    def max_message_tokens(self, fixed_overhead: int = 0) -> int:
        return max(512, self.max_prompt_tokens() - max(0, fixed_overhead))

    def total_with_overhead(
        self, messages: List[ChatMessage], fixed_overhead: int = 0
    ) -> int:
        return self.total_tokens(messages) + max(0, fixed_overhead)

    def should_compress(
        self,
        messages: List[ChatMessage],
        *,
        fixed_overhead: int = 0,
        force: bool = False,
    ) -> bool:
        if not messages:
            return False
        if force:
            return True
        total = self.total_with_overhead(messages, fixed_overhead)
        return (
            total >= self.compress_trigger_tokens() or total >= self.max_prompt_tokens()
        )

    def budget_status(
        self, messages: List[ChatMessage], *, fixed_overhead: int = 0
    ) -> Dict[str, int]:
        total = self.total_with_overhead(messages, fixed_overhead)
        trigger = self.compress_trigger_tokens()
        max_prompt = self.max_prompt_tokens()
        return {
            "total": total,
            "messages": self.total_tokens(messages),
            "overhead": max(0, fixed_overhead),
            "trigger": trigger,
            "max_prompt": max_prompt,
            "over_trigger": int(total >= trigger),
            "over_budget": int(total >= max_prompt),
        }

    async def summarize_transcript(
        self,
        transcript: str,
        *,
        pre_compression_hook: Optional[Callable[[str], Awaitable[None]]] = None,
        lang: str = "it",
    ) -> str:
        if pre_compression_hook:
            try:
                await pre_compression_hook(transcript)
            except Exception as exc:
                logger.warning("pre_compression_hook failed: %s", exc)
        transcript = (transcript or "").strip()
        if not transcript:
            return "[nessun contesto precedente da sintetizzare]"
        cap = int(os.getenv("AION_CONTEXT_COMPRESS_TRANSCRIPT_CHARS", "120000"))
        if len(transcript) > cap:
            transcript = transcript[:cap] + "\n[… transcript troncato per limite …]"
        try:
            summary_text = complete_text_sync(
                compaction_summary_prompt(lang),
                transcript,
                max_tokens=int(
                    os.getenv("AION_CONTEXT_COMPRESS_SUMMARY_MAX_TOKENS", "2000")
                ),
                timeout=float(
                    os.getenv("AION_CONTEXT_COMPRESS_SUMMARY_TIMEOUT", "120")
                ),
            )
        except Exception as exc:
            logger.warning("compression LLM failed: %s", exc)
            summary_text = "[compressione contesto non disponibile — riprova /compact]"
        return (summary_text or "").strip() or "[contesto storico non disponibile]"

    async def compress(
        self,
        messages: List[ChatMessage],
        pre_compression_hook: Optional[
            Callable[[List[ChatMessage]], Awaitable[None]]
        ] = None,
        *,
        transcript_override: Optional[str] = None,
        lang: str = "it",
    ) -> List[ChatMessage]:
        if not messages:
            return messages
        keep = (
            min(self.keep_last, max(1, len(messages) - 1))
            if len(messages) <= self.keep_last
            else self.keep_last
        )
        if len(messages) <= 1:
            return truncate_messages_to_prompt_budget(
                messages,
                max_prompt_tokens=self.max_prompt_tokens(),
                fixed_overhead=0,
                keep_last=1,
            )
        head = messages[:-keep]
        tail = messages[-keep:]
        if pre_compression_hook and not transcript_override:
            try:
                await pre_compression_hook(head)
            except Exception as exc:
                logger.warning("pre_compression_hook failed: %s", exc)

        if transcript_override is not None:
            transcript = transcript_override
        else:
            transcript = "\n".join(
                f"{m.role}: {chat_message_text(m)[:2500]}" for m in head
            )
        summary_text = await self.summarize_transcript(transcript, lang=lang)
        summary_msg = ChatMessage.from_user(
            format_compaction_block(summary_text, source_messages=len(head))
        )
        return [summary_msg] + tail

    async def compress_until_fits(
        self,
        messages: List[ChatMessage],
        *,
        fixed_overhead: int = 0,
        pre_compression_hook: Optional[
            Callable[[List[ChatMessage]], Awaitable[None]]
        ] = None,
        force: bool = False,
        transcript_override: Optional[str] = None,
        lang: str = "it",
    ) -> List[ChatMessage]:
        max_rounds = max(1, int(os.getenv("AION_CONTEXT_COMPRESS_MAX_ROUNDS", "3")))
        max_prompt = self.max_prompt_tokens()
        trigger = self.compress_trigger_tokens()
        out = list(messages)
        hook = pre_compression_hook
        used_transcript = transcript_override
        for round_idx in range(max_rounds):
            total = self.total_with_overhead(out, fixed_overhead)
            over_budget = total > max_prompt
            over_trigger = total >= trigger
            if not force and not over_budget and not over_trigger:
                break
            if len(out) <= 1 and not over_budget:
                break
            before = total
            out = await self.compress(
                out,
                hook,
                transcript_override=used_transcript if round_idx == 0 else None,
                lang=lang,
            )
            used_transcript = None
            hook = None
            force = False
            after = self.total_with_overhead(out, fixed_overhead)
            logger.info(
                "context_compress round=%d messages=%d tokens %d→%d trigger=%d max_prompt=%d",
                round_idx + 1,
                len(out),
                before,
                after,
                trigger,
                max_prompt,
            )
            if after <= max_prompt:
                break
        return truncate_messages_to_prompt_budget(
            out,
            max_prompt_tokens=max_prompt,
            fixed_overhead=fixed_overhead,
            keep_last=self.keep_last,
        )


def _replace_message_text(message: ChatMessage, text: str) -> ChatMessage:
    role = getattr(message, "role", None)
    role_s = str(role).lower() if role is not None else "user"
    meta = getattr(message, "meta", None) or {}
    if "assistant" in role_s:
        return ChatMessage.from_assistant(text, meta=meta)
    return ChatMessage.from_user(text, meta=meta)


def truncate_messages_to_prompt_budget(
    messages: List[ChatMessage],
    *,
    max_prompt_tokens: int,
    fixed_overhead: int = 0,
    keep_last: int = 1,
) -> List[ChatMessage]:
    if not messages:
        return messages
    out = list(messages)
    keep_last = max(1, keep_last)

    def _total() -> int:
        return sum(count_tokens(chat_message_text(m)) for m in out) + max(
            0, fixed_overhead
        )

    while len(out) > 0 and _total() > max_prompt_tokens:
        if len(out) > keep_last:
            out.pop(0)
            continue
        idx = 0
        text = chat_message_text(out[idx])
        if len(text) <= 256:
            if len(out) == 1:
                break
            out.pop(0)
            continue
        new_len = max(256, len(text) // 2)
        out[idx] = _replace_message_text(
            out[idx],
            text[:new_len] + "\n[… troncato per limite contesto …]",
        )
        if count_tokens(chat_message_text(out[idx])) >= count_tokens(text) * 0.9:
            break
    return out


def estimate_agent_overhead_tokens(agent: object) -> int:
    floor = overhead_floor_tokens()
    try:
        sp = getattr(agent, "system_prompt", None) or ""
        floor += count_tokens(sp if isinstance(sp, str) else str(sp))
        tools = getattr(agent, "tools", None) or []
        for tool in tools:
            spec = getattr(tool, "tool_spec", None)
            if spec is not None:
                try:
                    floor += count_tokens(json.dumps(spec, ensure_ascii=False))
                except (TypeError, ValueError):
                    floor += count_tokens(str(spec)[:16_000])
            else:
                floor += count_tokens(getattr(tool, "name", "") or "")
                floor += count_tokens(getattr(tool, "description", "") or "")
    except Exception as exc:
        logger.debug("estimate_agent_overhead_tokens: %s", exc)
    return floor


def estimate_full_prompt_tokens(
    agent: object, messages: List[ChatMessage]
) -> Dict[str, int]:
    overhead = estimate_agent_overhead_tokens(agent)
    msg_tokens = sum(count_tokens(chat_message_text(m)) for m in messages)
    comp = get_default_compressor()
    total = msg_tokens + overhead
    return {
        "messages": msg_tokens,
        "overhead": overhead,
        "total": total,
        "trigger": comp.compress_trigger_tokens(),
        "max_prompt": comp.max_prompt_tokens(),
    }


def log_context_budget(
    session_id: str,
    stats: Dict[str, int],
    *,
    will_compact: bool,
) -> None:
    line = (
        f">>> [CONTEXT] session={session_id[:8]} total={stats.get('total')} "
        f"msg={stats.get('messages')} overhead={stats.get('overhead')} "
        f"trigger={stats.get('trigger')} max_prompt={stats.get('max_prompt')} "
        f"compact={'YES' if will_compact else 'no'}"
    )
    print(line, flush=True)
    logger.warning(line)


def is_context_length_error(exc: BaseException) -> bool:
    from src.runtime.litellm_errors import is_context_length_error as _is_context_length_error

    return _is_context_length_error(exc)


def get_default_compressor() -> ContextCompressor:
    return ContextCompressor(
        window_size=model_context_window(),
        threshold=float(os.getenv("AION_CONTEXT_COMPRESS_THRESHOLD", "0.5")),
        keep_last=int(os.getenv("AION_CONTEXT_COMPRESS_KEEP_LAST", "6")),
    )
