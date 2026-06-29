"""Approval tool sensibili (Hermes FASE M) — estensione futura; default sempre allow."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger("aion.security.approval")


class ApprovalManager:
    async def check(
        self, tool_name: str, tool_input: Dict[str, Any], session_id: str
    ) -> Dict[str, Any]:
        if os.getenv("AION_APPROVAL_ENABLED", "1").lower() not in ("1", "true", "yes"):
            return {"action": "auto_allow", "rule": None}
        raw = (os.getenv("AION_APPROVAL_CRITICAL_TOOLS") or "").strip()
        if not raw:
            # ``draft_execution_plan`` ha già HITL via wait registry; aggiungerlo qui solo per doppio gate esplicito.
            raw = "sandbox_execute_python,sandbox_run_python_file,shell_execute"
        critical = {x.strip() for x in raw.split(",") if x.strip()}
        if tool_name in critical:
            return {"action": "ask", "rule": "critical_tool"}
        return {"action": "auto_allow", "rule": None}


approval_manager = ApprovalManager()
