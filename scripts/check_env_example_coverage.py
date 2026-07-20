#!/usr/bin/env python3
"""
Verifica copertura ``.env.example`` vs codice e script di upgrade.

Controlli (default: documentato = riga attiva **oppure** commentata ``# AION_*=``):

  1. Ogni ``os.getenv`` / ``os.environ.get`` su ``AION_*`` in ``src/`` è documentato in
     ``.env.example`` (``setup_aion_env.py`` include solo righe attive nel .env generato).
  2. Campi ``AionSettings`` in ``src/settings.py`` (Pydantic ``AION_`` + FIELD_NAME).
  3. Chiavi nei blocchi ``*_ENV_DEFAULTS`` di ``scripts/upgrade_core.py`` presenti come
     righe **attive** in ``.env.example``.

Uso:

  python scripts/check_env_example_coverage.py
  python scripts/check_env_example_coverage.py --strict          # solo righe attive per getenv
  python scripts/check_env_example_coverage.py --verbose
  python scripts/check_env_example_coverage.py --no-upgrade-check

Exit code 1 se mancano chiavi.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
SETTINGS = ROOT / "src/settings.py"
UPGRADE_CORE = ROOT / "scripts/upgrade_core.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "setup_aion_env", ROOT / "scripts" / "setup_aion_env.py"
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
_managed_keys_active = _mod._managed_keys  # type: ignore[attr-defined]

_GETENV_RE = re.compile(
    r"os\.getenv\(\s*['\"](AION_[A-Z0-9_]+)['\"]|os\.environ\.get\(\s*['\"](AION_[A-Z0-9_]+)['\"]"
)
_KEY_LINE_RE = re.compile(r"(AION_[A-Z0-9_]+)\s*=")
_UPGRADE_DEFAULT_RE = re.compile(r'"(AION_[A-Z0-9_]+)":\s*"([^"]*)"')


def _parse_example_keys(path: Path) -> tuple[set[str], set[str], set[str]]:
    """Return (active, commented_only, all_documented)."""
    active: set[str] = set()
    commented: set[str] = set()
    if not path.is_file():
        return active, commented, set()
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        is_comment = line.startswith("#")
        if is_comment:
            line = line.lstrip("#").strip()
        m = _KEY_LINE_RE.search(line)
        if not m:
            continue
        key = m.group(1)
        if is_comment:
            commented.add(key)
        else:
            active.add(key)
    documented = active | commented
    return active, commented - active, documented


def _keys_used_in_src() -> set[str]:
    out: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in _GETENV_RE.finditer(text):
            out.add(m.group(1) or m.group(2))
    return out


def _keys_from_settings() -> set[str]:
    if not SETTINGS.is_file():
        return set()
    text = SETTINGS.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"class AionSettings\b.*?(?=^@lru_cache|\Z)", text, re.M | re.S)
    if not m:
        return set()
    fields = re.findall(r"^\s+([a-z][a-z0-9_]*):\s", m.group(0), re.M)
    skip = {"model_config"}
    return {f"AION_{name.upper()}" for name in fields if name not in skip}


def _keys_from_upgrade_defaults() -> dict[str, str]:
    if not UPGRADE_CORE.is_file():
        return {}
    text = UPGRADE_CORE.read_text(encoding="utf-8", errors="ignore")
    out: dict[str, str] = {}
    for block in re.finditer(r"_\w+_ENV_DEFAULTS[^=]*=\s*\{([^}]*)\}", text, re.S):
        for km in _UPGRADE_DEFAULT_RE.finditer(block.group(1)):
            out[km.group(1)] = km.group(2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--strict",
        action="store_true",
        help="getenv: fallisce se la chiave non è una riga attiva (ignora commenti)",
    )
    ap.add_argument(
        "--no-upgrade-check",
        action="store_true",
        help="Non verificare che i default di upgrade_core siano righe attive in .env.example",
    )
    ap.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Elenca anche chiavi in example non trovate in src",
    )
    args = ap.parse_args()

    active, commented_only, documented = _parse_example_keys(EXAMPLE)
    used_getenv = _keys_used_in_src()
    settings_keys = _keys_from_settings()
    upgrade_defaults = _keys_from_upgrade_defaults()

    getenv_target = active if args.strict else documented
    getenv_missing = sorted(used_getenv - getenv_target)
    settings_missing = sorted(settings_keys - documented)
    upgrade_missing = sorted(set(upgrade_defaults) - active)

    print(f".env.example righe attive:              {len(active)}")
    print(f".env.example solo commentate:           {len(commented_only)}")
    print(f"AION_* getenv in src/:                  {len(used_getenv)}")
    print(f"AionSettings fields (AION_*):            {len(settings_keys)}")
    print(f"upgrade_core *_ENV_DEFAULTS keys:        {len(upgrade_defaults)}")

    failed = False

    if getenv_missing:
        failed = True
        mode = "attive" if args.strict else "documentate (attive o # commento)"
        print(f"\nERRORE: {len(getenv_missing)} chiavi getenv in src non {mode} in .env.example:\n")
        for k in getenv_missing:
            print(f"  {k}")

    if settings_missing:
        failed = True
        print(
            f"\nERRORE: {len(settings_missing)} campi AionSettings non documentati in .env.example:\n"
        )
        for k in settings_missing:
            print(f"  {k}")

    if not args.no_upgrade_check and upgrade_missing:
        failed = True
        print(
            f"\nERRORE: {len(upgrade_missing)} chiavi upgrade_core senza riga attiva in .env.example:\n"
        )
        for k in upgrade_missing:
            default = upgrade_defaults.get(k, "")
            print(f"  {k}={default}")

    if not failed:
        print("\nOK: copertura .env.example / settings / upgrade_core.")

    if args.verbose:
        extra_active = sorted(active - used_getenv - settings_keys)
        if extra_active:
            print(f"\nInfo: {len(extra_active)} chiavi attive solo in example (es.):\n")
            for k in extra_active[:30]:
                print(f"  {k}")
            if len(extra_active) > 30:
                print(f"  ... +{len(extra_active) - 30}")
        in_example_not_upgrade = sorted(active - set(upgrade_defaults.keys()))
        toolish = [
            k
            for k in in_example_not_upgrade
            if any(
                x in k
                for x in (
                    "STREAM_LOOP",
                    "MODEL_PROMPT",
                    "ARTIFACT",
                    "DOOM_LOOP",
                    "JSON_RECOVERY",
                    "VLLM_TOOL",
                    "LLM_CALL_AUDIT",
                    "MODEL_TOOL_POLICY",
                )
            )
        ]
        if toolish:
            print("\nInfo: chiavi tool-runtime attive in example ma fuori da upgrade_core defaults:")
            for k in toolish:
                print(f"  {k}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
