#!/usr/bin/env python3
"""Pre-download Chroma ONNX embeddings (Docker build / setup / upgrade)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.aion_env  # noqa: F401

from src.runtime.mempalace_warmup import warmup_chroma_embeddings


def main() -> int:
    ok = warmup_chroma_embeddings(force=True)
    if ok:
        print("OK: Chroma embedding model cached")
        return 0
    print("WARN: Chroma embedding warmup failed (see logs)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
