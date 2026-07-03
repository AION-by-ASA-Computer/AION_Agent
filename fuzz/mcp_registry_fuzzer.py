#!/usr/bin/env python3
"""Fuzz target for MCP registry document normalization."""

from __future__ import annotations

import json
import sys

import atheris

with atheris.instrument_imports():
    from src.mcp_registry_io import flatten_registry_document


def TestOneInput(data: bytes) -> None:
    if len(data) > 65536:
        return
    try:
        obj = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    flatten_registry_document(obj)


atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
