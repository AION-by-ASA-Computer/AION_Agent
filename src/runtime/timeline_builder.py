"""Build interleaved message timeline from SSE chunks (mirrors chat-ui reducer.ts)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.runtime.plan_display import (
    feed_plan_aware_display,
    strip_plan_blocks_for_chat_display,
)


def _seg_id(prefix: str, n: int) -> str:
    return f"{prefix}_{n}"


class TimelineBuilder:
    def __init__(self) -> None:
        self.segments: List[Dict[str, Any]] = []
        self._plan_capture_active = False
        self._plan_capture_phase = "none"
        self._plan_capture_pending = ""
        self._tool_steps: Dict[str, Dict[str, Any]] = {}
        self._tool_order: List[str] = []
        self._active_tool_by_id: Dict[str, str] = {}
        self._active_tool_by_name: Dict[str, str] = {}
        self._artifacts: Dict[str, Dict[str, Any]] = {}
        self._artifact_order: List[str] = []

    def apply_chunk(self, chunk: Dict[str, Any]) -> None:
        ctype = str(chunk.get("type") or "")

        if ctype == "token":
            piece = chunk.get("content")
            piece = piece if isinstance(piece, str) else ""
            filtered, self._plan_capture_phase, self._plan_capture_pending = (
                feed_plan_aware_display(
                    piece, self._plan_capture_phase, self._plan_capture_pending
                )
            )
            self._plan_capture_active = self._plan_capture_phase != "none"
            if filtered:
                self._append_text(filtered)
            return

        if ctype == "reasoning":
            piece = chunk.get("reasoning")
            if piece is None:
                text = ""
            elif isinstance(piece, str):
                text = piece
            else:
                try:
                    text = json.dumps(piece, ensure_ascii=False)
                except (TypeError, ValueError):
                    text = str(piece)
            self._append_reasoning(text)
            return

        if ctype == "tool_event":
            ev = chunk.get("event") or {}
            if not isinstance(ev, dict):
                return
            et = str(ev.get("type") or "")
            name = str(ev.get("name") or "tool")

            if et == "request_sync":
                sync_name = str(ev.get("tool_name") or ev.get("name") or "tool")
                tid = f"sync:{sync_name}"
                if tid not in self._tool_steps:
                    self._upsert_tool(
                        {
                            "kind": "tool",
                            "id": tid,
                            "name": sync_name,
                            "input": {"_pending": True},
                            "status": "running",
                        }
                    )
                    self._tool_steps[tid] = {
                        "id": tid,
                        "name": sync_name,
                        "input": {"_pending": True},
                        "status": "running",
                    }
                    if tid not in self._tool_order:
                        self._tool_order.append(tid)
                    self._active_tool_by_name[sync_name] = tid
            elif et == "tool_start":
                tid = (
                    str(ev.get("id") or "").strip() or f"{name}:{len(self._tool_order)}"
                )
                self._upsert_tool(
                    {
                        "kind": "tool",
                        "id": tid,
                        "name": name,
                        "input": ev.get("input"),
                        "status": "running",
                    }
                )
                self._tool_steps[tid] = {
                    "id": tid,
                    "name": name,
                    "input": ev.get("input"),
                    "status": "running",
                }
                if tid not in self._tool_order:
                    self._tool_order.append(tid)
                self._active_tool_by_name[name] = tid
                eid = str(ev.get("id") or "").strip()
                if eid:
                    self._active_tool_by_id[eid] = tid
            elif et == "tool_end":
                tid = self._resolve_tool_id(ev, name)
                cur = self._tool_steps.get(tid) or {
                    "id": tid,
                    "name": name,
                    "input": ev.get("input") or {},
                }
                output = str(ev.get("output") or "")
                seg = {
                    "kind": "tool",
                    "id": tid,
                    "name": cur.get("name") or name,
                    "input": cur.get("input")
                    if cur.get("input") is not None
                    else ev.get("input"),
                    "output": output,
                    "status": "done",
                }
                if isinstance(ev.get("tokens_in"), int):
                    seg["tokens_in"] = ev["tokens_in"]
                if isinstance(ev.get("tokens_out"), int):
                    seg["tokens_out"] = ev["tokens_out"]
                self._upsert_tool(seg)
                self._tool_steps[tid] = {**cur, "output": output, "status": "done"}
                if tid not in self._tool_order:
                    self._tool_order.append(tid)
                self._active_tool_by_name.pop(name, None)
                eid = str(ev.get("id") or "").strip()
                if eid:
                    self._active_tool_by_id.pop(eid, None)
            elif et == "tool_error":
                tid = self._resolve_tool_id(ev, name)
                cur = self._tool_steps.get(tid) or {
                    "id": tid,
                    "name": name,
                    "input": ev.get("input") or {},
                }
                seg = {
                    "kind": "tool",
                    "id": tid,
                    "name": cur.get("name") or name,
                    "input": cur.get("input")
                    if cur.get("input") is not None
                    else ev.get("input"),
                    "output": str(ev.get("error") or ""),
                    "status": "error",
                    "isError": True,
                }
                self._upsert_tool(seg)
                self._tool_steps[tid] = {
                    **cur,
                    "output": str(ev.get("error") or ""),
                    "isError": True,
                    "status": "error",
                }
                if tid not in self._tool_order:
                    self._tool_order.append(tid)
                self._active_tool_by_name.pop(name, None)
                eid = str(ev.get("id") or "").strip()
                if eid:
                    self._active_tool_by_id.pop(eid, None)
            return

        if ctype == "artifact_start":
            art = chunk.get("artifact") or {}
            if not isinstance(art, dict):
                return
            aid = str(art.get("identifier") or "unknown")
            if aid not in self._artifacts:
                self._artifact_order.append(aid)
            self._artifacts[aid] = {
                "id": aid,
                "title": str(art.get("title") or aid),
                "artType": str(art.get("type") or "text"),
                "buffer": "",
            }
            a_seg = {
                "kind": "artifact",
                "id": aid,
                "title": str(art.get("title") or aid),
                "artType": str(art.get("type") or "text"),
                "buffer": "",
            }
            idx = next(
                (
                    i
                    for i, s in enumerate(self.segments)
                    if s.get("kind") == "artifact" and s.get("id") == aid
                ),
                -1,
            )
            if idx >= 0:
                self.segments[idx] = a_seg
            else:
                self.segments.append(a_seg)
            return

        if ctype == "artifact_content":
            aid = chunk.get("artifact_id")
            ids = (
                [str(aid)]
                if aid and str(aid) in self._artifacts
                else list(self._artifact_order)
            )
            piece = str(chunk.get("content") or "")
            for art_id in ids:
                a = self._artifacts.get(art_id)
                if not a:
                    continue
                buf = (a.get("buffer") or "") + piece
                self._artifacts[art_id] = {**a, "buffer": buf}
                idx = next(
                    (
                        i
                        for i, s in enumerate(self.segments)
                        if s.get("kind") == "artifact" and s.get("id") == art_id
                    ),
                    -1,
                )
                if idx >= 0:
                    self.segments[idx] = {**self.segments[idx], "buffer": buf}
            return

        if ctype == "artifact_end":
            art = chunk.get("artifact") or {}
            if not isinstance(art, dict):
                return
            aid = str(art.get("identifier") or "")
            cur = self._artifacts.get(aid)
            if not cur:
                return
            self._artifacts[aid] = {
                **cur,
                "savedPath": str(art.get("path") or ""),
                "version": int(art.get("version") or 1),
                "execution": str(art["execution"])
                if art.get("execution") is not None
                else None,
            }
            idx = next(
                (
                    i
                    for i, s in enumerate(self.segments)
                    if s.get("kind") == "artifact" and s.get("id") == aid
                ),
                -1,
            )
            if idx >= 0:
                self.segments[idx] = {
                    **self.segments[idx],
                    "savedPath": str(art.get("path") or ""),
                    "version": int(art.get("version") or 1),
                    "execution": str(art["execution"])
                    if art.get("execution") is not None
                    else None,
                    "buffer": "",
                }
            return

        if ctype == "final":
            text = chunk.get("text")
            if isinstance(text, str) and text.strip():
                visible = strip_plan_blocks_for_chat_display(text)
                if visible:
                    self._append_text(visible)
            return

    def to_list(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for seg in self.segments:
            s = dict(seg)
            if s.get("kind") == "artifact":
                s["buffer"] = ""
            out.append(s)
        return out

    def to_json(self) -> Optional[str]:
        segs = self.to_list()
        if not segs:
            return None
        return json.dumps(segs, ensure_ascii=False)

    def _append_reasoning(self, piece: str) -> None:
        if not piece:
            return
        if self.segments and self.segments[-1].get("kind") == "reasoning":
            last = self.segments[-1]
            self.segments[-1] = {**last, "content": (last.get("content") or "") + piece}
            return
        self.segments.append(
            {
                "kind": "reasoning",
                "id": _seg_id("reasoning", len(self.segments)),
                "content": piece,
            }
        )

    def _append_text(self, piece: str) -> None:
        if not piece:
            return
        if self.segments and self.segments[-1].get("kind") == "text":
            last = self.segments[-1]
            self.segments[-1] = {**last, "content": (last.get("content") or "") + piece}
            return
        self.segments.append(
            {
                "kind": "text",
                "id": _seg_id("text", len(self.segments)),
                "content": piece,
            }
        )

    def _upsert_tool(self, seg: Dict[str, Any]) -> None:
        tid = seg.get("id")
        idx = next(
            (
                i
                for i, s in enumerate(self.segments)
                if s.get("kind") == "tool" and s.get("id") == tid
            ),
            -1,
        )
        if idx >= 0:
            self.segments[idx] = seg
        else:
            self.segments.append(seg)

    def _resolve_tool_id(self, ev: Dict[str, Any], name: str) -> str:
        eid = str(ev.get("id") or "").strip()
        if eid and eid in self._tool_steps:
            return eid
        if eid and eid in self._active_tool_by_id:
            return self._active_tool_by_id[eid]
        if name in self._active_tool_by_name:
            return self._active_tool_by_name[name]
        for i in range(len(self._tool_order) - 1, -1, -1):
            key = self._tool_order[i]
            if self._tool_steps.get(key, {}).get("name") == name:
                return key
        return eid or name
