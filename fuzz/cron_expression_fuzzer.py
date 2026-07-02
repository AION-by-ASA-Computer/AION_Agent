#!/usr/bin/env python3
"""Fuzz target for cron expression validation."""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import atheris

with atheris.instrument_imports():
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


atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
