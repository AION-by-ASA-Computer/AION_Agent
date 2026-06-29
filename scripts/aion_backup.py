#!/usr/bin/env python3
"""Tar essential config + DB (see plan §8.3)."""
from __future__ import annotations

import argparse
import json
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    arc = out_dir / f"aion_backup_{ts}.tar.gz"
    manifest: dict = {"components": [], "ts": ts}
    with tarfile.open(arc, "w:gz") as tf:
        for rel in (
            "data/aion.db",
            "data/chat_memory.db",
            "config/default.yaml",
            "config/mcp_registry.yaml",
            "config/mcp_registry.local.yaml",
            "data/plugins",
            "data/deep_research",
        ):
            p = ROOT / rel
            if p.exists():
                tf.add(p, arcname=rel, recursive=True)
                manifest["components"].append(rel)
    (out_dir / f"aion_backup_{ts}.manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(arc)
    return arc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=ROOT / "data" / "_backups")
    args = ap.parse_args()
    main(args.output)
