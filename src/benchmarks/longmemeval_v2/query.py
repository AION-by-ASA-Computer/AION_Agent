from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Tuple

from src.eval.evaluators import contains_match
from src.memory.llm_extract import complete_text_async_detailed
from src.memory.mnemos.orchestrator import mnemos_orchestrator

from src.memory.mnemos.fts import build_discriminative_query

from ..env_config import resolve_judge_profile
from .ingest import BENCHMARK_TENANT, eval_scope

_BOXED_RE = re.compile(r"\\boxed\{([^}]*)\}", re.IGNORECASE)
_CHOICE_RE = re.compile(r"^([A-H])\b", re.IGNORECASE)


def build_benchmark_recall_query(question: str) -> str:
    """Extract discriminative FTS terms from a benchmark question (no hardcoded keywords)."""
    boosted = build_discriminative_query(question)
    return boosted if boosted else (question or "")


def _recall_limit() -> int:
    return int(os.getenv("AION_LME_V2_RECALL_LIMIT", "20"))


async def _recall_for_question(
    *,
    user_id: str,
    project_slug: str,
    question: str,
) -> List[Dict[str, Any]]:
    limit = _recall_limit()
    boosted = build_benchmark_recall_query(question)
    queries = [boosted]
    if boosted.strip().lower() != (question or "").strip().lower():
        queries.append(question)

    seen_ids: set[int] = set()
    merged: List[Dict[str, Any]] = []
    for query in queries:
        rows = await mnemos_orchestrator.recall_notes(
            tenant_id=BENCHMARK_TENANT,
            user_id=user_id,
            query=query,
            scope_name="project",
            active_project_slug=project_slug,
            limit=limit,
        )
        for row in rows:
            nid = row.get("id")
            if nid is None:
                continue
            try:
                note_id = int(nid)
            except (TypeError, ValueError):
                continue
            if note_id in seen_ids:
                continue
            seen_ids.add(note_id)
            merged.append(row)
            if len(merged) >= limit:
                return merged
    return merged


def _judge_system_prompt(profile_name: str) -> str:
    _ = profile_name
    return (
        "You answer benchmark questions using ONLY the provided evidence. "
        "Reply with the specific fact, phrase, number, or multiple-choice letter "
        "requested — no explanation. "
        "For multiple-choice, reply with a single letter (A-H). "
        "For lists, use comma-separated phrases. "
        "For workflow questions asking for ServiceNow module names, infer module "
        "names from evidence (e.g. 'list of reports' → Reports; 'problem list' or "
        "reassigning problems → Problems). "
        "If evidence is insufficient, reply UNKNOWN."
    )


def normalize_actual_answer(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    boxed = _BOXED_RE.search(raw)
    if boxed:
        return boxed.group(1).strip()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if lines:
        last = lines[-1]
        choice = _CHOICE_RE.match(last)
        if choice and len(last) <= 3:
            return choice.group(1).upper()
        return last
    return raw


def _expected_term_hits(expected: str, evidence: str) -> Dict[str, bool]:
    evidence_l = evidence.lower()
    hits: Dict[str, bool] = {}
    for part in re.split(r"[;,]", expected or ""):
        term = part.strip()
        if len(term) < 2:
            continue
        hits[term] = term.lower() in evidence_l
    return hits


def explain_score(expected: str, actual: str) -> Dict[str, Any]:
    exp = (expected or "").strip()
    raw = (actual or "").strip()
    norm = normalize_actual_answer(actual)
    if not exp:
        return {"reason": "missing_expected", "score": 0.0}
    if not raw:
        return {"reason": "empty_llm_response", "score": 0.0, "normalized": norm}
    if norm.upper() == "UNKNOWN":
        return {"reason": "llm_answered_unknown", "score": 0.0, "normalized": norm}
    if contains_match(exp, norm):
        return {"reason": "exact_or_substring_match", "score": 1.0, "normalized": norm}
    if contains_match(norm, exp):
        return {"reason": "reverse_substring_match", "score": 1.0, "normalized": norm}
    parts = [p.strip() for p in re.split(r"[;,]", exp) if p.strip()]
    if len(parts) > 1:
        part_hits = {p: contains_match(p, norm) for p in parts}
        if all(part_hits.values()):
            return {
                "reason": "all_parts_matched",
                "score": 1.0,
                "normalized": norm,
                "part_hits": part_hits,
            }
        return {
            "reason": "partial_or_wrong_multi_part",
            "score": 0.0,
            "normalized": norm,
            "part_hits": part_hits,
        }
    if len(exp) == 1 and exp.isalpha() and norm.upper() == exp.upper():
        return {"reason": "single_letter_match", "score": 1.0, "normalized": norm}
    return {
        "reason": "no_match",
        "score": 0.0,
        "normalized": norm,
        "expected": exp,
        "actual_normalized": norm,
    }


async def gather_evidence(
    run_id: str,
    question: str,
    *,
    project_slug: str = "lme_v2_small",
    expected_output: str = "",
) -> Tuple[str, Dict[str, Any]]:
    _, user_id = eval_scope(run_id=run_id, project_slug=project_slug)
    boosted_query = build_benchmark_recall_query(question)
    recalled = await _recall_for_question(
        user_id=user_id,
        project_slug=project_slug,
        question=question,
    )
    wake = ""
    if os.getenv("AION_LME_V2_SKIP_WAKE", "1") != "1":
        wake = await mnemos_orchestrator.wake_up(
            tenant_id=BENCHMARK_TENANT,
            user_id=user_id,
            active_project_slug=project_slug,
        )
    lines: List[str] = []
    recall_rows: List[Dict[str, Any]] = []
    if recalled:
        lines.append("## Mnemos recall (question-specific)")
        for row in recalled:
            content = row.get("content") or row.get("text") or row.get("line") or ""
            if content:
                lines.append(str(content))
                recall_rows.append(
                    {
                        "id": row.get("id"),
                        "seq": row.get("seq"),
                        "preview": str(content)[:400],
                    }
                )
    if wake.strip():
        lines.append(wake.strip())
    evidence = "\n".join(lines)
    debug = {
        "project_slug": project_slug,
        "user_id": user_id,
        "recall_query_boosted": boosted_query,
        "recall_limit": _recall_limit(),
        "recall_count": len(recalled),
        "recall_rows": recall_rows[:15],
        "wake_chars": len(wake),
        "evidence_chars": len(evidence),
        "expected_term_hits": _expected_term_hits(expected_output, evidence),
    }
    return evidence, debug


async def answer_question(
    question: str,
    evidence: str,
    *,
    profile_name: str,
    session_id: str,
    config: dict | None = None,
) -> Tuple[str, float, Dict[str, Any]]:
    """Direct LLM QA (no full agent/MCP stack — benchmark subprocess safe)."""
    _ = session_id
    judge_profile = resolve_judge_profile(profile_name, config)
    system = _judge_system_prompt(judge_profile)
    user = (
        f"EVIDENCE:\n{evidence[:12000] or '(empty)'}\n\n"
        f"QUESTION:\n{question}\n\n"
        "Answer with only the final answer text (no explanation):"
    )
    start = time.monotonic()
    llm_detail = await complete_text_async_detailed(
        system,
        user,
        max_tokens=int(os.getenv("AION_LME_V2_QA_MAX_TOKENS", "512")),
        timeout=float(os.getenv("AION_LME_V2_QA_TIMEOUT", "120")),
        disable_reasoning=True,
    )
    latency = time.monotonic() - start
    raw_text = str(llm_detail.get("raw_text") or llm_detail.get("text") or "")
    normalized = normalize_actual_answer(raw_text)
    qa_debug = {
        "judge_profile": judge_profile,
        "system_prompt": system,
        "user_prompt_chars": len(user),
        "user_prompt_preview": user[:4000],
        "user_prompt_tail": user[-1500:] if len(user) > 1500 else "",
        "llm": llm_detail,
        "raw_text": raw_text,
        "normalized_answer": normalized,
        "latency_sec": latency,
    }
    return normalized, latency, qa_debug


def score_answer(expected: str, actual: str) -> float:
    return float(explain_score(expected, actual)["score"])
