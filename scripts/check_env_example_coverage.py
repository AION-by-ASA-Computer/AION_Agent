#!/usr/bin/env python3
"""
Verifica copertura .env.example vs codice: ogni ``os.getenv`` / ``os.environ.get`` su chiavi
``AION_*`` in ``src/`` deve comparire come riga **attiva** (non commentata) in ``.env.example``,
altrimenti lo script ``setup_aion_env.py`` non la includerà nel .env generato.

  python scripts/check_env_example_coverage.py
  python scripts/check_env_example_coverage.py --verbose

Exit code 1 se mancano chiavi.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "setup_aion_env", ROOT / "scripts" / "setup_aion_env.py"
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
_managed_keys = _mod._managed_keys  # type: ignore[attr-defined]

_GETENV_RE = re.compile(
    r"os\.getenv\(\s*['\"](AION_[A-Z0-9_]+)['\"]|os\.environ\.get\(\s*['\"](AION_[A-Z0-9_]+)['\"]"
)


def _keys_used_in_src() -> set[str]:
    out: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in _GETENV_RE.finditer(text):
            out.add(m.group(1) or m.group(2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-v", "--verbose", action="store_true", help="Elenca anche chiavi in example non trovate in src")
    args = ap.parse_args()

    managed = _managed_keys()
    used = _keys_used_in_src()
    missing = sorted(used - managed)
    extra = sorted(managed - used)

    print(f"managed keys (.env.example righe attive): {len(managed)}")
    print(f"AION_* getenv in src/:                  {len(used)}")
    if missing:
        print(f"\nERRORE: {len(missing)} chiavi usate in src ma assenti da .env.example (attive):\n")
        for k in missing:
            print(f"  {k}")
        return 1
    print("OK: tutte le chiavi AION_* lette via getenv/environ.get in src sono in .env.example.")
    if args.verbose and extra:
        print(f"\nInfo: {len(extra)} chiavi solo in example (non trovate da questo scan), es.:\n")
        for k in extra[:40]:
            print(f"  {k}")
        if len(extra) > 40:
            print(f"  ... +{len(extra) - 40}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
