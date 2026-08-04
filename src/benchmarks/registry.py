from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional


@dataclass
class BenchmarkSpec:
    id: str
    title: str
    description: str
    tier: Optional[str] = None
    coming_soon: bool = False
    dataset_ready_fn: Optional[Callable[[], bool]] = None


RunnerFn = Callable[..., Awaitable[Dict[str, Any]]]

BENCHMARK_REGISTRY: Dict[str, BenchmarkSpec] = {}
_RUNNERS: Dict[str, RunnerFn] = {}


def register_benchmark(
    spec: BenchmarkSpec,
    runner: RunnerFn,
) -> None:
    BENCHMARK_REGISTRY[spec.id] = spec
    _RUNNERS[spec.id] = runner


def get_benchmark(benchmark_id: str) -> BenchmarkSpec:
    if benchmark_id not in BENCHMARK_REGISTRY:
        raise KeyError(f"unknown benchmark: {benchmark_id}")
    return BENCHMARK_REGISTRY[benchmark_id]


def get_runner(benchmark_id: str) -> RunnerFn:
    if benchmark_id not in _RUNNERS:
        raise KeyError(f"no runner for benchmark: {benchmark_id}")
    return _RUNNERS[benchmark_id]


def catalog_entries() -> list[dict[str, Any]]:
    out = []
    for spec in BENCHMARK_REGISTRY.values():
        ready = False
        if spec.dataset_ready_fn:
            try:
                ready = bool(spec.dataset_ready_fn())
            except Exception:
                ready = False
        out.append(
            {
                "id": spec.id,
                "title": spec.title,
                "description": spec.description,
                "tier": spec.tier,
                "coming_soon": spec.coming_soon,
                "dataset_ready": ready,
            }
        )
    return out


def mnemos_config_snapshot(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    import os

    keys = [
        "AION_LTM_WAKE_MAX_ROWS",
        "AION_LTM_WAKE_MAX_CHARS",
        "AION_MNEMOS_RECALL_LIMIT",
        "AION_LTM_MIN_IMPORTANCE",
        "AION_LTM_EXTRACT",
        "AION_LTM_PREFIX_IN_USER",
    ]
    snap = {k: os.getenv(k) for k in keys}
    if extra:
        snap.update(extra)
    return snap


def write_run_config(run_id: str, payload: Dict[str, Any]) -> None:
    from .paths import run_artifact_dir

    path = run_artifact_dir(run_id) / "config.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
