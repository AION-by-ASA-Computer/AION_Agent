from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def benchmark_data_dir() -> Path:
    raw = os.getenv("AION_BENCHMARK_DATA_DIR", "data/benchmarks")
    p = Path(raw)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p


def run_artifact_dir(run_id: str) -> Path:
    d = benchmark_data_dir() / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_log_path(run_id: str) -> Path:
    return run_artifact_dir(run_id) / "run.log"
