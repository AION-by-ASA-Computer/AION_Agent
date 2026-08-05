"""Structured benchmark logging to terminal + run artifacts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .paths import run_artifact_dir, run_log_path


def benchmark_verbose() -> bool:
    return os.getenv("AION_BENCHMARK_VERBOSE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


class RunLogger:
    """Mirror log lines to stdout and ``runs/<id>/run.log``; rich rows to ``debug.jsonl``."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.log_path = run_log_path(run_id)
        self.debug_path = run_artifact_dir(run_id) / "debug.jsonl"
        self.verbose = benchmark_verbose()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def line(self, phase: str, message: str, **fields: Any) -> None:
        suffix = ""
        if fields and self.verbose:
            suffix = " " + json.dumps(fields, ensure_ascii=False, default=str)
        text = f"[{phase}] {message}{suffix}"
        print(text, flush=True)
        with open(self.log_path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")

    def debug_record(self, record: Dict[str, Any]) -> None:
        payload = {"ts": self._ts(), "run_id": self.run_id, **record}
        with open(self.debug_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        if self.verbose and record.get("phase") == "query":
            self._print_case_summary(payload)

    def _print_case_summary(self, rec: Dict[str, Any]) -> None:
        case_id = rec.get("case_id", "?")
        score = rec.get("score")
        expected = rec.get("expected_output", "")
        actual = rec.get("actual_output", "")
        self.line(
            "query",
            f"case {case_id} score={score} expected={expected!r} actual={actual!r}",
            llm_model=rec.get("llm", {}).get("model"),
            finish_reason=rec.get("llm", {}).get("finish_reason"),
            recall_count=rec.get("evidence", {}).get("recall_count"),
            eval_function=rec.get("eval_function"),
            score_reason=rec.get("score_debug", {}).get("reason"),
        )
        llm = rec.get("llm") or {}
        raw = llm.get("raw_text")
        if raw is not None and str(raw) != str(actual):
            self.line("query", f"  llm_raw={str(raw)[:300]!r}")
        reason = (rec.get("score_debug") or {}).get("reason")
        if reason:
            self.line("query", f"  score_reason={reason}")
        hints = (rec.get("evidence") or {}).get("expected_term_hits") or []
        if hints is not None:
            self.line("query", f"  expected_in_evidence={hints}")
