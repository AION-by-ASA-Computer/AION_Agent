"""Research job handler — background tasks, persistence, visual reports."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .deep_research import DeepResearcher
from .llm_bridge import probe_model
from .research_utils import is_low_quality, strip_thinking
from .visual_report import generate_visual_report

logger = logging.getLogger("aion.research")


def _trace(msg: str) -> None:
    """Stdout + structured log — visible in dev-api.sh like DEBUG_THREAD lines."""
    print(f">>> [DEEP_RESEARCH] {msg}", flush=True)
    logger.info(msg)

_handler: Optional["ResearchHandler"] = None


def research_data_dir() -> Path:
    raw = (os.getenv("AION_DEEP_RESEARCH_DATA_DIR") or "data/deep_research").strip()
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _bounded_int(value, *, default: int, minimum: int, maximum: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, n))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _normalize_max_rounds(max_rounds: int) -> int:
    """0 or negative means use env default (agent tool passes 0 = auto)."""
    if max_rounds <= 0:
        return _bounded_int(
            _env_int("AION_DEEP_RESEARCH_MAX_ROUNDS", 8),
            default=8,
            minimum=1,
            maximum=32,
        )
    return _bounded_int(max_rounds, default=8, minimum=1, maximum=32)


def _normalize_max_time(max_time: int) -> int:
    if max_time <= 0:
        return _bounded_int(
            _env_int("AION_DEEP_RESEARCH_MAX_TIME", 600),
            default=600,
            minimum=60,
            maximum=3600,
        )
    return _bounded_int(max_time, default=600, minimum=60, maximum=3600)


def deep_research_enabled() -> bool:
    return (os.getenv("AION_DEEP_RESEARCH_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def max_concurrent_per_owner() -> int:
    return max(1, _env_int("AION_DEEP_RESEARCH_MAX_CONCURRENT", 2))


def _progress_label(event: dict) -> str:
    """Human-readable one-line summary for UI activity log."""
    phase = str(event.get("phase") or "")
    round_n = event.get("round")
    round_s = f" — round {round_n}" if round_n else ""

    if phase == "probing":
        return "Verifica connessione al modello LLM…"
    if phase == "planning":
        return f"Pianificazione strategia di ricerca{round_s}…"
    if phase == "searching":
        preview = (event.get("query_preview") or "").strip()
        nq = event.get("queries")
        if preview:
            short = preview if len(preview) <= 90 else preview[:87] + "…"
            return f"Ricerca web{round_s}: «{short}»"
        if nq:
            return f"Generazione di {nq} query di ricerca{round_s}…"
        total = event.get("total_sources")
        if total is not None:
            return f"Avvio ricerche web{round_s} ({total} fonti già analizzate)…"
        return f"Ricerca sul web{round_s}…"
    if phase == "reading":
        title = (event.get("title") or event.get("url") or "").strip()
        if title:
            short = title if len(title) <= 100 else title[:97] + "…"
            return f"Lettura ed estrazione: {short}"
        new_src = event.get("new_sources")
        if new_src:
            return f"Estrazione da {new_src} nuove fonti{round_s}…"
        return f"Lettura delle fonti trovate{round_s}…"
    if phase == "analyzing":
        tf = event.get("total_findings")
        if tf is not None:
            return f"Analisi di {tf} finding raccolti{round_s}…"
        return f"Sintesi e analisi dei risultati{round_s}…"
    if phase == "writing":
        msg = (event.get("message") or "").strip()
        if msg:
            return msg
        return "Writing final report…"
    if phase == "warning":
        return f"Warning: {event.get('message') or 'step failed, continuing…'}"
    if phase == "error":
        return f"Error: {event.get('message') or 'research interrupted'}"
    msg = (event.get("message") or "").strip()
    if msg:
        return msg
    return phase or "In progress…"


class ResearchHandler:
    """Background deep research with in-memory registry + JSON persistence."""

    def __init__(self) -> None:
        self._active_tasks: Dict[str, dict] = {}
        research_data_dir()

    def _count_running_for_owner(self, owner: str) -> int:
        n = 0
        for entry in self._active_tasks.values():
            if entry.get("owner") == owner and entry.get("status") == "running":
                n += 1
        return n

    def start_research(
        self,
        session_id: str,
        query: str,
        *,
        max_time: int = 300,
        hard_timeout: Optional[int] = None,
        on_complete: Optional[Callable] = None,
        prior_report: str = "",
        prior_findings: Optional[List[Dict]] = None,
        prior_urls: Optional[Set[str]] = None,
        max_rounds: int = 20,
        category: Optional[str] = None,
        extraction_timeout: Optional[int] = None,
        extraction_concurrency: Optional[int] = None,
        owner: str = "",
        chat_session_id: str = "",
    ) -> dict:
        if not deep_research_enabled():
            raise RuntimeError("Deep research is disabled (AION_DEEP_RESEARCH_ENABLED=0)")

        owner = owner or ""
        if owner and self._count_running_for_owner(owner) >= max_concurrent_per_owner():
            raise RuntimeError(
                f"Max concurrent research jobs ({max_concurrent_per_owner()}) reached"
            )

        if session_id in self._active_tasks:
            existing = self._active_tasks[session_id]
            if existing.get("status") == "running":
                self.cancel_research(session_id)

        if hard_timeout is None:
            raw = _env_int("AION_DEEP_RESEARCH_RUN_TIMEOUT", 1800)
            hard_timeout = None if raw <= 0 else _bounded_int(raw, default=1800, minimum=60, maximum=86400)

        max_rounds = _normalize_max_rounds(max_rounds)
        max_time = _normalize_max_time(max_time)

        entry: Dict[str, Any] = {
            "task": None,
            "researcher": None,
            "query": query,
            "status": "running",
            "progress": {},
            "activities": [],
            "result": None,
            "started_at": time.time(),
            "category": category,
            "owner": owner,
            "chat_session_id": (chat_session_id or "").strip(),
        }
        self._active_tasks[session_id] = entry
        self._persist_running(session_id, entry)
        _trace(
            f"started session={session_id} owner={owner!r} chat={entry['chat_session_id']!r} "
            f"max_rounds={max_rounds} max_time={max_time}s query={query[:100]!r}"
        )

        def on_progress(event: dict) -> None:
            payload = dict(event)
            payload["ts"] = time.time()
            payload["label"] = _progress_label(payload)
            entry["progress"] = payload
            last_phase = entry.get("_last_trace_phase")
            phase = payload.get("phase")
            if phase and phase != last_phase:
                entry["_last_trace_phase"] = phase
                _trace(
                    f"session={session_id} phase={phase} "
                    f"{(payload.get('label') or '')[:100]}"
                )
            activities: List[dict] = entry.setdefault("activities", [])
            activities.append(payload)
            if len(activities) > 100:
                entry["activities"] = activities[-100:]
            self._persist_running(session_id, entry)

        async def _run() -> None:
            try:
                result = await asyncio.wait_for(
                    self._run_research(
                        query,
                        max_time=max_time,
                        progress_callback=on_progress,
                        task_entry=entry,
                        prior_report=prior_report,
                        prior_findings=prior_findings,
                        prior_urls=prior_urls,
                        max_rounds=max_rounds,
                        category=category,
                        extraction_timeout=extraction_timeout,
                        extraction_concurrency=extraction_concurrency,
                    ),
                    timeout=hard_timeout,
                )
                entry["result"] = result
                entry["status"] = "done"
                self._save_result(session_id, entry)
                _trace(
                    f"completed session={session_id} owner={entry.get('owner')!r} "
                    f"duration={time.time() - float(entry.get('started_at') or time.time()):.1f}s"
                )
                if on_complete:
                    sources = entry.get("sources", [])
                    findings = self._extract_raw_findings(
                        entry["researcher"].findings if entry.get("researcher") else []
                    )
                    on_complete(session_id, result, sources, findings)
            except asyncio.TimeoutError:
                logger.error("Research hard timeout for session %s", session_id)
                researcher = entry.get("researcher")
                if researcher and getattr(researcher, "evolving_report", ""):
                    entry["result"] = researcher.evolving_report
                    entry["status"] = "done"
                    self._save_result(session_id, entry)
                else:
                    entry["status"] = "error"
                    entry["result"] = f"Research timed out after {hard_timeout}s."
                on_progress({"phase": "error", "message": f"Timed out after {hard_timeout}s"})
            except asyncio.CancelledError:
                entry["status"] = "cancelled"
                raise
            except Exception as e:
                logger.error("Background research failed: %s", e, exc_info=True)
                entry["result"] = str(e)
                entry["status"] = "error"
                self._save_result(session_id, entry)
                _trace(
                    f"failed session={session_id} owner={entry.get('owner')!r} "
                    f"error={str(e)[:200]}"
                )

        self._schedule_background_coro(entry, _run())
        return {"session_id": session_id, "status": "running", "query": query}

    def _schedule_background_coro(self, entry: dict, coro) -> None:
        """Schedule on the running loop (API) or the main loop from agent worker threads."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                entry["task"] = asyncio.create_task(coro)
                return
        except RuntimeError:
            pass

        from src.main import _GLOBAL_LOOP

        main_loop = _GLOBAL_LOOP
        if main_loop is None or not main_loop.is_running():
            raise RuntimeError(
                "Deep research event loop unavailable; use the Research panel or POST /research/start"
            )
        entry["future"] = asyncio.run_coroutine_threadsafe(coro, main_loop)

    async def _run_research(
        self,
        query: str,
        *,
        max_time: int,
        progress_callback: Optional[Callable],
        task_entry: dict,
        prior_report: str,
        prior_findings: Optional[List[Dict]],
        prior_urls: Optional[Set[str]],
        max_rounds: int,
        category: Optional[str],
        extraction_timeout: Optional[int],
        extraction_concurrency: Optional[int],
    ) -> str:
        if progress_callback:
            progress_callback({"phase": "probing", "max_rounds": max_rounds})
        await probe_model()

        from src.runtime.native_tools.web_providers import web_search_availability

        ws = web_search_availability()
        if not ws.get("any_enabled"):
            warn = (
                "Nessun provider web search abilitato (Tavily/Brave/SearXNG). "
                "Imposta AION_WEB_SEARCH_*_ENABLED=1 in .env"
            )
            _trace(f"web search unavailable: {warn}")
            if progress_callback:
                progress_callback({"phase": "warning", "message": warn})
        else:
            _trace(f"web search providers: {','.join(ws.get('enabled') or [])}")

        max_report_tokens = _env_int("AION_DEEP_RESEARCH_MAX_TOKENS", 16384)
        ext_timeout = _bounded_int(
            extraction_timeout if extraction_timeout is not None else _env_int("AION_DEEP_RESEARCH_EXTRACTION_TIMEOUT", 90),
            default=90,
            minimum=15,
            maximum=3600,
        )
        ext_conc = _bounded_int(
            extraction_concurrency
            if extraction_concurrency is not None
            else _env_int("AION_DEEP_RESEARCH_EXTRACTION_CONCURRENCY", 3),
            default=3,
            minimum=1,
            maximum=12,
        )

        researcher = DeepResearcher(
            llm_endpoint="",
            llm_model=os.getenv("AION_MODEL", ""),
            max_rounds=max_rounds,
            min_rounds=min(3, max_rounds),
            max_time=max_time,
            max_report_tokens=max_report_tokens,
            extraction_timeout=ext_timeout,
            extraction_concurrency=ext_conc,
            progress_callback=progress_callback,
            category=category,
        )
        task_entry["researcher"] = researcher

        start = time.time()
        report = await researcher.research(
            query,
            prior_report=prior_report,
            prior_findings=prior_findings,
            prior_urls=prior_urls,
        )
        elapsed = time.time() - start
        stats = researcher.get_stats()
        task_entry["raw_report"] = strip_thinking(report)
        task_entry["stats"] = stats
        return self._format_research_report(query, report, stats, elapsed)

    def get_status(self, session_id: str) -> Optional[dict]:
        avg = self.get_avg_duration()
        if session_id in self._active_tasks:
            entry = self._active_tasks[session_id]
            out = {
                "status": entry["status"],
                "progress": entry.get("progress") or {},
                "activities": list(entry.get("activities") or []),
                "query": entry.get("query", ""),
                "started_at": entry.get("started_at", 0),
                "chat_session_id": entry.get("chat_session_id") or "",
            }
            if avg is not None:
                out["avg_duration"] = round(avg, 1)
            return out
        path = research_data_dir() / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("consumed"):
                    return None
                st = data.get("status", "done")
                if st == "running":
                    self._recover_orphaned_session(session_id, data)
                    st = data.get("status", "done")
                return {
                    "status": st,
                    "progress": data.get("progress") or {},
                    "activities": list(data.get("activities") or []),
                    "query": data.get("query", ""),
                    "started_at": data.get("started_at", 0),
                    "chat_session_id": data.get("chat_session_id") or "",
                }
            except Exception:
                pass
        return None

    def list_active_for_owner(
        self, owner: str, *, chat_session_id: Optional[str] = None
    ) -> List[dict]:
        """Running jobs in memory + on disk (survives page refresh; not server restart)."""
        self._recover_stale_running_on_disk()
        seen: set[str] = set()
        items: List[dict] = []
        for sid, entry in self._active_tasks.items():
            if entry.get("owner") != owner or entry.get("status") != "running":
                continue
            if not self._matches_chat_session(entry, chat_session_id):
                continue
            seen.add(sid)
            items.append(self._active_job_payload(sid, entry))
        for path in research_data_dir().glob("*.json"):
            sid = path.stem
            if sid in seen:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("owner") != owner or data.get("status") != "running":
                continue
            if not self._matches_chat_session(data, chat_session_id):
                continue
            if sid not in self._active_tasks:
                self._recover_orphaned_session(sid, data)
                if data.get("status") != "running":
                    continue
            entry = self._active_tasks.get(sid)
            if entry and entry.get("status") == "running":
                items.append(self._active_job_payload(sid, entry))
        items.sort(key=lambda x: x.get("started_at") or 0, reverse=True)
        return items

    @staticmethod
    def _matches_chat_session(data: dict, chat_session_id: Optional[str]) -> bool:
        if not chat_session_id:
            return True
        cid = (data.get("chat_session_id") or "").strip()
        return bool(cid) and cid == chat_session_id.strip()

    @staticmethod
    def _active_job_payload(session_id: str, entry: dict) -> dict:
        return {
            "session_id": session_id,
            "query": entry.get("query", ""),
            "status": entry.get("status", "running"),
            "progress": entry.get("progress") or {},
            "activities": list(entry.get("activities") or []),
            "started_at": entry.get("started_at", 0),
            "chat_session_id": entry.get("chat_session_id") or "",
        }

    def _persist_running(self, session_id: str, entry: dict) -> None:
        if entry.get("status") != "running":
            return
        path = research_data_dir() / f"{session_id}.json"
        try:
            data = {
                "query": entry.get("query"),
                "status": "running",
                "progress": entry.get("progress") or {},
                "activities": list(entry.get("activities") or [])[-100:],
                "category": entry.get("category"),
                "started_at": entry.get("started_at"),
                "owner": entry.get("owner", ""),
                "chat_session_id": entry.get("chat_session_id") or "",
            }
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug("persist running research %s: %s", session_id, e)

    def _recover_stale_running_on_disk(self) -> None:
        for path in research_data_dir().glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("status") != "running":
                continue
            sid = path.stem
            if sid in self._active_tasks and self._active_tasks[sid].get("status") == "running":
                continue
            self._recover_orphaned_session(sid, data)

    def _recover_orphaned_session(self, session_id: str, data: dict) -> None:
        """Mark disk-only running jobs as interrupted after server restart."""
        if data.get("status") != "running":
            return
        if session_id in self._active_tasks:
            return
        data["status"] = "interrupted"
        data["result"] = (
            "Research interrupted (server restart or lost session). "
            "Start a new research run on the same topic."
        )
        data["completed_at"] = time.time()
        try:
            path = research_data_dir() / f"{session_id}.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            logger.warning(
                "Deep research orphaned session=%s owner=%r query=%r — marked interrupted",
                session_id,
                data.get("owner"),
                (data.get("query") or "")[:80],
            )
        except Exception as e:
            logger.error("recover orphaned research %s: %s", session_id, e)

    def cancel_research(self, session_id: str) -> bool:
        entry = self._active_tasks.get(session_id)
        if not entry or entry.get("status") != "running":
            return False
        researcher = entry.get("researcher")
        if researcher:
            researcher.cancel()
        task = entry.get("task")
        if task and not task.done():
            task.cancel()
        future = entry.get("future")
        if future and not future.done():
            future.cancel()
        entry["status"] = "cancelled"
        return True

    def get_result(self, session_id: str) -> Optional[str]:
        entry = self._active_tasks.get(session_id)
        if entry and entry.get("status") in ("done", "error", "cancelled"):
            return entry.get("result")
        path = research_data_dir() / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("consumed"):
                    return None
                return data.get("result")
            except Exception:
                pass
        return None

    def get_sources(self, session_id: str) -> Optional[list]:
        entry = self._active_tasks.get(session_id)
        if entry:
            if entry.get("sources"):
                return entry["sources"]
            researcher = entry.get("researcher")
            if researcher and researcher.findings:
                return self._extract_sources(researcher.findings)
        path = research_data_dir() / f"{session_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8")).get("sources")
            except Exception:
                pass
        return None

    def get_raw_findings(self, session_id: str) -> Optional[list]:
        entry = self._active_tasks.get(session_id)
        if entry:
            researcher = entry.get("researcher")
            if researcher and researcher.findings:
                return self._extract_raw_findings(researcher.findings)
        path = research_data_dir() / f"{session_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8")).get("raw_findings")
            except Exception:
                pass
        return None

    def load_json(self, session_id: str) -> Optional[dict]:
        path = research_data_dir() / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def owns(self, session_id: str, owner: str) -> bool:
        entry = self._active_tasks.get(session_id)
        if entry is not None:
            return entry.get("owner", "") == owner
        data = self.load_json(session_id)
        if data is None:
            return False
        return data.get("owner", "") == owner

    def list_library(
        self,
        owner: str,
        *,
        search: str = "",
        sort: str = "recent",
        limit: int = 50,
        archived: Optional[bool] = None,
        chat_session_id: Optional[str] = None,
    ) -> List[dict]:
        items: List[dict] = []
        q = (search or "").strip().lower()
        for path in research_data_dir().glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("owner") != owner:
                continue
            if not self._matches_chat_session(data, chat_session_id):
                continue
            if archived is not None and bool(data.get("archived")) != archived:
                continue
            query = data.get("query") or ""
            if q and q not in query.lower():
                continue
            sid = path.stem
            items.append(
                {
                    "id": sid,
                    "query": query,
                    "category": data.get("category") or "",
                    "source_count": len(data.get("sources") or []),
                    "status": data.get("status", "done"),
                    "duration": (data.get("completed_at") or 0) - (data.get("started_at") or 0),
                    "rounds": (data.get("stats") or {}).get("Rounds"),
                    "started_at": data.get("started_at", 0),
                    "completed_at": data.get("completed_at", 0),
                    "archived": bool(data.get("archived")),
                }
            )
        if sort == "oldest":
            items.sort(key=lambda x: x.get("started_at") or 0)
        elif sort == "alpha":
            items.sort(key=lambda x: (x.get("query") or "").lower())
        else:
            items.sort(key=lambda x: x.get("completed_at") or x.get("started_at") or 0, reverse=True)
        return items[: max(1, min(limit, 200))]

    def delete_research(self, session_id: str) -> bool:
        self._active_tasks.pop(session_id, None)
        path = research_data_dir() / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def set_archived(self, session_id: str, archived: bool = True) -> bool:
        path = research_data_dir() / f"{session_id}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["archived"] = archived
            path.write_text(json.dumps(data), encoding="utf-8")
            return True
        except Exception:
            return False

    def clear_result(self, session_id: str) -> None:
        self._active_tasks.pop(session_id, None)
        path = research_data_dir() / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["consumed"] = True
                path.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass

    def get_report_html(self, session_id: str) -> Optional[str]:
        data = self.load_json(session_id)
        if not data:
            return None
        report_md = data.get("raw_report") or data.get("result", "")
        return generate_visual_report(
            question=data.get("query", ""),
            report_markdown=report_md,
            sources=data.get("sources"),
            stats=data.get("stats"),
            category=data.get("category"),
            session_id=session_id,
            hidden_images=data.get("hidden_images") or [],
        )

    def hide_image(self, session_id: str, image_url: str) -> bool:
        path = research_data_dir() / f"{session_id}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            hidden = list(data.get("hidden_images") or [])
            if image_url not in hidden:
                hidden.append(image_url)
                data["hidden_images"] = hidden
                path.write_text(json.dumps(data), encoding="utf-8")
            return True
        except Exception:
            return False

    def unhide_all_images(self, session_id: str) -> bool:
        path = research_data_dir() / f"{session_id}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["hidden_images"] = []
            path.write_text(json.dumps(data), encoding="utf-8")
            return True
        except Exception:
            return False

    def get_avg_duration(self) -> Optional[float]:
        durations: List[float] = []
        for path in research_data_dir().glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("status") == "done":
                    started = data.get("started_at", 0)
                    completed = data.get("completed_at", 0)
                    if started and completed and completed > started:
                        durations.append(completed - started)
            except Exception:
                continue
        return sum(durations) / len(durations) if durations else None

    def _save_result(self, session_id: str, entry: dict) -> None:
        try:
            sources: List[dict] = []
            raw_findings: List[dict] = []
            researcher = entry.get("researcher")
            if researcher and researcher.findings:
                sources = self._extract_sources(researcher.findings)
                raw_findings = self._extract_raw_findings(researcher.findings)
            entry["sources"] = sources
            path = research_data_dir() / f"{session_id}.json"
            data = {
                "query": entry.get("query"),
                "status": entry.get("status"),
                "result": entry.get("result"),
                "raw_report": entry.get("raw_report", ""),
                "sources": sources,
                "raw_findings": raw_findings,
                "stats": entry.get("stats"),
                "category": entry.get("category"),
                "started_at": entry.get("started_at"),
                "completed_at": time.time(),
                "owner": entry.get("owner", ""),
                "chat_session_id": entry.get("chat_session_id") or "",
                "progress": entry.get("progress") or {},
                "activities": list(entry.get("activities") or [])[-100:],
            }
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            logger.info("Research saved to %s", path)
        except Exception as e:
            logger.error("Failed to save research: %s", e)

    @staticmethod
    def _extract_sources(findings: list) -> list:
        seen: set[str] = set()
        sources: list = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            url = f.get("url", "")
            title = f.get("title", "") or url
            summary = f.get("summary", "") or f.get("evidence", "")
            if url and url not in seen and not is_low_quality(summary):
                seen.add(url)
                entry = {"url": url, "title": title}
                og = f.get("og_image", "")
                if og:
                    entry["image"] = og
                sources.append(entry)
        return sources

    @staticmethod
    def _extract_raw_findings(findings: list) -> list:
        items: list = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            url = f.get("url", "")
            title = f.get("title") or "Untitled"
            summary = f.get("summary", "")
            evidence = f.get("evidence", "")
            content = summary if summary else (evidence[:2000] if evidence else "")
            if url and content and not is_low_quality(content):
                items.append({"url": url, "title": title, "summary": content})
        return items

    @staticmethod
    def _format_research_report(query: str, full_report: str, stats: dict, elapsed: float) -> str:
        full_report = strip_thinking(full_report) or ""
        summary = " | ".join(
            [
                f"**Duration:** {elapsed:.1f}s",
                f"**Rounds:** {stats.get('Rounds', '?')}",
                f"**Queries:** {stats.get('Queries', '?')}",
                f"**URLs Analyzed:** {stats.get('URLs', '?')}",
            ]
        )
        return f"---\n{summary}\n---\n\n{full_report}"


def get_research_handler() -> ResearchHandler:
    global _handler
    if _handler is None:
        _handler = ResearchHandler()
    return _handler


def new_research_session_id(prefix: str = "rp") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
