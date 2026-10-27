#!/usr/bin/env python3
"""Esporta lo schema OpenAPI del backend.

  python scripts/export_openapi.py --full openapi.json      # schema completo (asset di release)
  python scripts/export_openapi.py --contract /tmp/c.json   # solo le route del contratto
  python scripts/export_openapi.py --update                 # riscrive lo snapshot committato

Lo snapshot (``docs/api-and-runtime/contract/openapi-contract.json``) è
confrontato da ``src/test/test_openapi_contract.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"scritto {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full", type=Path, help="schema completo")
    parser.add_argument("--contract", type=Path, help="solo le route del contratto")
    parser.add_argument(
        "--update", action="store_true", help="riscrive lo snapshot del contratto"
    )
    args = parser.parse_args()
    if not (args.full or args.contract or args.update):
        parser.error("indicare --full, --contract o --update")

    # Lo schema non dipende da questi flag, ma l'import dell'app sì.
    os.environ["AION_API_DOCS_ENABLED"] = "1"
    sys.path.insert(0, str(ROOT))
    from src.api.contract_diff import SNAPSHOT_PATH, contract_openapi
    from src.api.main import app

    full = app.openapi()
    if args.full:
        _write(args.full, full)
    if args.contract:
        _write(args.contract, contract_openapi(full))
    if args.update:
        _write(SNAPSHOT_PATH, contract_openapi(full))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
