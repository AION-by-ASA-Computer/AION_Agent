"""Apply benchmark run config (Mnemos env knobs, judge profile)."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


def apply_mnemos_env(config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Set AION_* env vars from run config for the benchmark subprocess."""
    applied: Dict[str, str] = {}
    cfg = config or {}
    mnemos = cfg.get("mnemos") if isinstance(cfg.get("mnemos"), dict) else cfg

    for key, value in mnemos.items():
        if not isinstance(key, str) or not key.startswith("AION_"):
            continue
        if value is None:
            continue
        sval = str(value).strip()
        if not sval:
            continue
        os.environ[key] = sval
        applied[key] = sval
    return applied


def resolve_judge_profile(profile_name: str, config: Optional[Dict[str, Any]] = None) -> str:
    cfg = config or {}
    return str(
        cfg.get("judge_profile")
        or os.getenv("AION_LME_V2_JUDGE_PROFILE")
        or profile_name
        or "aion_std"
    ).strip()


def resolve_project_slug(run_id: str, config: Optional[Dict[str, Any]] = None) -> str:
    """Isolated Mnemos project scope per benchmark run."""
    cfg = config or {}
    explicit = cfg.get("project_slug")
    if explicit:
        return str(explicit).strip()
    return f"lme_{run_id}"


def apply_benchmark_isolation_env(
    *,
    tenant_id: str = "benchmark",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Env vars so agent turns do not mutate or pollute benchmark memory."""
    applied: Dict[str, str] = {}
    defaults = {
        "AION_DEFAULT_TENANT_ID": tenant_id,
        "AION_LTM_EXTRACT": "0",
        "AION_LTM_PREFIX_IN_USER": "0",
        "AION_LTM_WAKE_MAX_ROWS": "0",
        "AION_LTM_WAKE_MAX_CHARS": "0",
        "AION_SKILL_DISTILL_ENABLED": "0",
        "AION_CONTEXT_COMPRESS_ENABLED": "0",
        "AION_STM_MAX_TURNS": "1",
        "AION_MNEMOS_READONLY_TOOLS": "1",
        "AION_MNEMOS_FTS_PHRASE_QUERY": "1",
        "AION_MNEMOS_RECALL_LIMIT": os.getenv("AION_LME_V2_RECALL_LIMIT", "20"),
        "AION_LME_V2_COMPRESS_SCOPE": "0",
        "AION_LME_V2_SKIP_WAKE": "1",
        "AION_LME_V2_MAX_CHUNKS_PER_TRAJ": "0",
        "AION_LME_V2_MAX_STATES_PER_TRAJ": "0",
        "AION_LME_V2_MAX_TREE_CHARS": "0",
    }
    cfg = config or {}
    overrides = cfg.get("benchmark_env") if isinstance(cfg.get("benchmark_env"), dict) else {}
    for key, value in {**defaults, **overrides}.items():
        if not key.startswith("AION_"):
            continue
        sval = str(value).strip()
        os.environ[key] = sval
        applied[key] = sval
    return applied
