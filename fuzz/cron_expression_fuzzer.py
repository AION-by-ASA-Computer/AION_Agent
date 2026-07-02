#!/usr/bin/env python3
"""Fuzz target for cron expression validation."""
from __future__ import annotations

import sys

import atheris

sys.path.insert(0, ".")

with atheris.instrument_import():
    from src.runtime.cron_expression import validate_cron_expression


def TestOneInput(data: bytes) -> None:
    if len(data) > 256:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    try:
        validate_cron_expression(text)
    except ValueError:
        pass


def main() -> None:
    atheris.instrument_all()
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
