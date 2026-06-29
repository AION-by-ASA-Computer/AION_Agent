"""Detect Plan Mode responses that violate sidebar-plan contract."""

from __future__ import annotations

import re

_PLAN_TAG = re.compile(r"<plan[\s>]", re.I)
_FORBIDDEN_ANYWHERE = re.compile(
    r"(from\s+docx\s+import|import\s+docx\b|sys\.path\.insert|"
    r"def\s+create_\w*course|def\s+create_ml|WD_ALIGN_PARAGRAPH|"
    r"Progetto di Forecasting|Proposta di Collaborazione|"
    r"Formazione \+ Sviluppo Modelli Predittivi|NeuralForecast / Nixtla)",
    re.I,
)
_CODE_FENCE = re.compile(r"```(?:python|py)?\s", re.I)


def response_looks_like_deliverable_leak(text: str) -> bool:
    body = text or ""
    return bool(_FORBIDDEN_ANYWHERE.search(body) or _CODE_FENCE.search(body))


def plan_mode_response_valid(
    text: str,
    *,
    plan_registered: bool = False,
    tool_first: bool = True,
) -> tuple[bool, str]:
    """
    Returns (ok, reason). In tool-first mode only deliverable leaks fail validation.
    Legacy text-parser mode still requires a <plan> tag when no plan was registered.
    """
    if plan_registered:
        return True, "ok_plan_registered"
    body = text or ""
    if response_looks_like_deliverable_leak(body):
        return False, "deliverable_code_without_plan"
    if tool_first:
        return True, "ok_tool_first"
    if not _PLAN_TAG.search(body):
        return False, "missing_plan_tag"
    if _FORBIDDEN_ANYWHERE.search(body):
        return False, "deliverable_or_wrong_template_in_body"
    low = body.lower()
    close = low.rfind("</plan>")
    if close >= 0 and len(body) - close > 80:
        tail = body[close + 6 :].strip()
        if len(tail) > 40:
            return False, "trailing_content_after_plan"
    return True, "ok"
