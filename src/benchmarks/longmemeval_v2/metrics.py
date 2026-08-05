from __future__ import annotations

import statistics
from typing import Any, Dict, List


def aggregate_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "accuracy_overall": 0.0,
            "accuracy_by_ability": {},
            "accuracy_by_eval_function": {},
            "latency_p50_ms": 0,
            "latency_p95_ms": 0,
            "evidence_chars_avg": 0,
            "case_count": 0,
            "image_cases": 0,
        }

    scores = [
        float(r.get("score", 0))
        for r in rows
        if r.get("score") is not None and r.get("skipped") != "skipped_image"
    ]
    latencies_ms = [
        float(r.get("latency_sec", 0)) * 1000
        for r in rows
        if r.get("skipped") != "skipped_image"
    ]
    evidence_lens = [
        len(str(r.get("evidence", "")))
        for r in rows
        if r.get("skipped") != "skipped_image"
    ]

    def _grouped(key: str, default: str) -> Dict[str, Dict[str, Any]]:
        buckets: Dict[str, List[float]] = {}
        for r in rows:
            if r.get("skipped") == "skipped_image" or r.get("score") is None:
                continue
            buckets.setdefault(str(r.get(key) or default), []).append(
                float(r.get("score", 0))
            )
        return {
            k: {"accuracy": (sum(v) / len(v) if v else 0.0), "cases": len(v)}
            for k, v in sorted(buckets.items())
        }

    by_ability: Dict[str, List[float]] = {}
    for r in rows:
        if r.get("skipped") == "skipped_image" or r.get("score") is None:
            continue
        ab = str(r.get("ability", "unknown"))
        by_ability.setdefault(ab, []).append(float(r.get("score", 0)))

    accuracy_by_ability = {
        k: (sum(v) / len(v) if v else 0.0) for k, v in sorted(by_ability.items())
    }
    accuracy_by_eval_function = _grouped("eval_function", "unspecified")

    latencies_ms.sort()
    p50 = statistics.median(latencies_ms) if latencies_ms else 0
    p95_idx = max(0, int(len(latencies_ms) * 0.95) - 1)
    p95 = latencies_ms[p95_idx] if latencies_ms else 0

    return {
        "accuracy_overall": (sum(scores) / len(scores)) if scores else 0.0,
        "accuracy_by_ability": accuracy_by_ability,
        "accuracy_by_eval_function": accuracy_by_eval_function,
        "latency_p50_ms": round(p50, 1),
        "latency_p95_ms": round(p95, 1),
        "evidence_chars_avg": round(sum(evidence_lens) / len(evidence_lens), 1)
        if evidence_lens
        else 0,
        "case_count": len([r for r in rows if r.get("skipped") != "skipped_image"]),
        "questions_total": len(rows),
        "image_cases": sum(1 for r in rows if r.get("requires_image")),
        "skipped_image": sum(1 for r in rows if r.get("skipped") == "skipped_image"),
    }


def render_report_md(run_id: str, metrics: Dict[str, Any]) -> str:
    lines = [
        f"# Benchmark report: {run_id}",
        "",
        f"- Overall accuracy: **{metrics.get('accuracy_overall', 0) * 100:.1f}%**",
        f"- Cases: {metrics.get('case_count', 0)}",
        f"- Latency p50: {metrics.get('latency_p50_ms')} ms",
        f"- Latency p95: {metrics.get('latency_p95_ms')} ms",
        "",
        "## By ability",
        "",
    ]
    for k, v in (metrics.get("accuracy_by_ability") or {}).items():
        lines.append(f"- {k}: {v * 100:.1f}%")

    by_eval = metrics.get("accuracy_by_eval_function") or {}
    if by_eval:
        lines.extend(["", "## By official eval_function", ""])
        for k, v in by_eval.items():
            lines.append(f"- {k}: {v['accuracy'] * 100:.1f}% ({v['cases']} cases)")

    image_cases = metrics.get("image_cases") or 0
    skipped = metrics.get("skipped_image") or 0
    if image_cases or skipped:
        lines.extend(
            [
                "",
                f"> {image_cases} question(s) ship an image; {skipped} skipped "
                f"(text-only runner).",
            ]
        )
    lines.append("")
    return "\n".join(lines)
