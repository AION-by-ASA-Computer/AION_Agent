#!/usr/bin/env python3
"""Fuzz target for MCP registry document normalization."""
from __future__ import annotations

import json
import sys

import atheris

sys.path.insert(0, ".")

with atheris.instrument_import():
    from src.mcp_registry_io import flatten_registry_document


def TestOneInput(data: bytes) -> None:
    if len(data) > 65536:
        return
    try:
        obj = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    flatten_registry_document(obj)


def main() -> None:
    atheris.instrument_all()
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
