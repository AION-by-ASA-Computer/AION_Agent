"""Risolve native_tool_groups del profilo in Haystack Tool."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List

from haystack.tools import Tool

from .factory_table import NATIVE_TOOL_FACTORIES
from .registry_io import get_bundle, load_merged_native_tool_registry

if TYPE_CHECKING:
    from ...agent_profile import AgentProfile

logger = logging.getLogger(__name__)


def native_registry_content_hash() -> str:
    """Frammento stabile per cache agent (invalida quando cambia il registry)."""
    try:
        blob = json.dumps(
            load_merged_native_tool_registry(), sort_keys=True, default=str
        )
    except Exception:
        blob = ""
    return hashlib.md5(blob.encode("utf-8")).hexdigest()[:16]


def load_native_tools(
    profile: "AgentProfile", session_id: str, user_id: str
) -> List[Tool]:
    groups = getattr(profile, "native_tool_groups", None) or []
    if not groups:
        return []
    tools: List[Tool] = []
    seen_names: set[str] = set()
    for gid in groups:
        bundle = get_bundle(str(gid))
        if not bundle:
            logger.warning("native_tool_groups: bundle sconosciuto %r", gid)
            continue
        tool_ids = bundle.get("tools") or []
        if not isinstance(tool_ids, list):
            continue
        for tid in tool_ids:
            tid_s = str(tid).strip()
            factory = NATIVE_TOOL_FACTORIES.get(tid_s)
            if not factory:
                logger.warning(
                    "native tool id sconosciuto %r nel bundle %r", tid_s, gid
                )
                continue
            try:
                t = factory(session_id, user_id, profile)
            except ValueError as exc:
                logger.debug("native tool %r skipped: %s", tid_s, exc)
                continue
            if t.name in seen_names:
                continue
            seen_names.add(t.name)
            tools.append(t)
    return tools
