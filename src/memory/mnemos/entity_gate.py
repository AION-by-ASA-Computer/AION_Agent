"""Gate evaluation for Mnemos entity index (Phase 4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def evaluate_entity_gate(
    metrics_path: Path,
    *,
    alias_threshold: int = 6,
) -> Dict[str, Any]:
    """Return gate decision based on alias_coref category score."""
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    by_cat = data.get("accuracy_by_category") or {}
    alias = by_cat.get("alias_coref") or {}
    passed = int(alias.get("passed") or 0)
    total = int(alias.get("total") or 0)
    build_entity_index = total > 0 and passed < alias_threshold
    return {
        "alias_coref_passed": passed,
        "alias_coref_total": total,
        "threshold": alias_threshold,
        "build_entity_index": build_entity_index,
        "recommendation": (
            "Enable AION_MNEMOS_ENTITY_RECALL=1 and seed aliases"
            if build_entity_index
            else "Entity index not required; hybrid recall is sufficient"
        ),
    }
