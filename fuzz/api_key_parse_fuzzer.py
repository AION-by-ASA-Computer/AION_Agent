#!/usr/bin/env python3
"""Fuzz target for API key header parsing."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import atheris

_ROOT = Path(__file__).resolve().parents[1]
_API_KEY_PATH = _ROOT / "src" / "api" / "auth" / "api_key.py"


def _load_parse_api_key():
    """Load api_key.py without importing src.api.auth (pulls in FastAPI)."""
    spec = importlib.util.spec_from_file_location("aion_fuzz_api_key", _API_KEY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load fuzz module from {_API_KEY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.parse_api_key


with atheris.instrument_imports():
    parse_api_key = _load_parse_api_key()


def TestOneInput(data: bytes) -> None:
    if len(data) > 512:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    parse_api_key(text)


atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
