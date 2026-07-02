#!/usr/bin/env python3
"""Fuzz target for API key header parsing."""
from __future__ import annotations

import atheris
import sys

with atheris.instrument_imports():
    from src.security.api_key_parse import parse_api_key


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
