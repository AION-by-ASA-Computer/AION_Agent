#!/usr/bin/env python3
"""Fuzz target for API key header parsing."""
from __future__ import annotations

import sys

import atheris

sys.path.insert(0, ".")

with atheris.instrument_import():
    from src.api.auth.api_key import parse_api_key


def TestOneInput(data: bytes) -> None:
    if len(data) > 512:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    parse_api_key(text)


def main() -> None:
    atheris.instrument_all()
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
