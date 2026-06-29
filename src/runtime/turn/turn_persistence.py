"""Persist tool steps, attachments, and streaming assistant content during a turn."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.runtime.tool_step_queue import queue_tool_step as _queue_tool_step

logger = logging.getLogger(__name__)


class TurnPersistence:
    def __init__(
        self,
        *,
        session_id: str,
        history_manager: Any,
        assistant_message_id: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> None:
        self.session_id = session_id
        self.history_manager = history_manager
        self.assistant_message_id = assistant_message_id
        self.metadata_json = metadata_json
        self.pending_db_steps: List[Dict[str, Any]] = []
        self.pending_db_attachments: List[Dict[str, Any]] = []
        self.pending_step_ids: Dict[str, str] = {}
        self._persisted_step_sigs: set[str] = set()
        self._stream_flush_interval = float(
            os.getenv("AION_STREAM_DB_FLUSH_SEC", "0.75")
        )
        self._last_stream_flush_at = 0.0
        self.assistant_message_persisted = False

    def queue_attachment(
        self,
        *,
        storage_key: str,
        original_name: str,
        mime: str,
        size_bytes: int,
        kind: str = "artifact",
    ) -> None:
        if not storage_key:
            return
        self.pending_db_attachments.append(
            {
                "storage_key": storage_key,
                "original_name": original_name or Path(storage_key).name,
                "mime": mime or "application/octet-stream",
                "size_bytes": max(0, int(size_bytes or 0)),
                "kind": kind,
            }
        )

    def queue_tool_step(
        self,
        evt: Dict[str, Any],
        *,
        is_error: bool = False,
        is_start: bool = False,
    ) -> None:
        _queue_tool_step(
            self.pending_db_steps,
            self.pending_step_ids,
            evt,
            is_error=is_error,
            is_start=is_start,
        )

    @staticmethod
    def _step_persist_sig(step: Dict[str, Any]) -> str:
        sid = str(step.get("step_id") or "").strip()
        if sid:
            return f"id:{sid}:upd={bool(step.get('pending_update'))}"
        return (
            f"{step.get('name')}:{hash(str(step.get('input') or ''))}:"
            f"{hash(str(step.get('output') or ''))}"
        )

    async def persist_pending_turn_records(
        self,
        message_id: Optional[str],
        *,
        only_new: bool = False,
        include_attachments: bool = True,
    ) -> None:
        seen_updates: set[str] = set()
        for step in self.pending_db_steps:
            sig = self._step_persist_sig(step)
            if only_new and sig in self._persisted_step_sigs:
                continue
            try:
                sid = step.get("step_id")
                meta: Dict[str, Any] = {}
                if "tokens_in" in step:
                    meta["tokens_in"] = step["tokens_in"]
                if "tokens_out" in step:
                    meta["tokens_out"] = step["tokens_out"]
                meta_str = json.dumps(meta) if meta else step.get("metadata_json")

                if step.get("pending_update") and sid:
                    if sid in seen_updates:
                        continue
                    seen_updates.add(sid)
                    await self.history_manager.update_step(
                        sid,
                        output=step.get("output"),
                        is_error=bool(step.get("is_error")),
                        metadata_json=meta_str,
                    )
                    if only_new:
                        self._persisted_step_sigs.add(sig)
                    continue
                await self.history_manager.add_step(
                    self.session_id,
                    name=step["name"],
                    type=step["type"],
                    input=step["input"],
                    output=step["output"],
                    is_error=bool(step["is_error"]),
                    message_id=message_id,
                    step_id=sid,
                    metadata_json=meta_str,
                )
                if only_new:
                    self._persisted_step_sigs.add(sig)
            except Exception as db_err:
                logger.warning("Failed to persist tool step: %s", db_err)
        if not include_attachments:
            return
        for att in self.pending_db_attachments:
            try:
                await self.history_manager.add_attachment(
                    self.session_id,
                    storage_key=att["storage_key"],
                    original_name=att["original_name"],
                    mime=att["mime"],
                    size_bytes=att["size_bytes"],
                    kind=att["kind"],
                    message_id=message_id,
                )
            except Exception as db_err:
                logger.warning("Failed to persist artifact attachment: %s", db_err)

    async def flush_assistant_stream_content(
        self,
        *,
        full_response: List[str],
        full_reasoning: List[str],
        profile_name: str,
        user_id: str,
        loop_time: float,
        force: bool = False,
    ) -> None:
        if not self.assistant_message_id:
            return
        if (
            not force
            and (loop_time - self._last_stream_flush_at) < self._stream_flush_interval
        ):
            return
        self._last_stream_flush_at = loop_time
        body = "".join(full_response)
        reasoning_text = "".join(full_reasoning) or None
        try:
            await self.history_manager.upsert_message_content(
                self.session_id,
                self.assistant_message_id,
                "assistant",
                body,
                profile_name=profile_name,
                user_id=user_id,
                reasoning=reasoning_text,
                metadata_json=self.metadata_json,
            )
            self.assistant_message_persisted = True
        except Exception as db_err:
            logger.warning("Failed to flush assistant stream content: %s", db_err)
