#!/usr/bin/env python3
"""Print a Markdown table of all AionSettings fields and their defaults/descriptions.

Usage:
    python scripts/generate-env-docs.py
    python scripts/generate-env-docs.py > docs/configuration/env-reference.md
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the repo root is on sys.path so src imports work without installation.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Load .env before importing settings.
import src.aion_env  # noqa: F401  must be first

from src.settings import AionSettings


def _type_name(annotation) -> str:
    """Return a concise human-readable type string."""
    if annotation is None:
        return "Any"
    name = getattr(annotation, "__name__", None)
    if name:
        return name
    # Handle Optional[X] → X | None
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())
    if origin is type(None):
        return "None"
    if origin is not None:
        import typing

        if origin is typing.Union:
            parts = [_type_name(a) for a in args]
            return " | ".join(parts)
    return str(annotation)


def _field_default(field_info) -> str:
    """Return the default value as a string, or '—' if required."""
    sentinel = getattr(field_info, "default", ...)
    if sentinel is ...:
        factory = getattr(field_info, "default_factory", None)
        if factory is not None:
            return f"`{factory()!r}`"
        return "*(required)*"
    if sentinel is None:
        return "`None`"
    if isinstance(sentinel, bool):
        return f"`{'true' if sentinel else 'false'}`"
    if isinstance(sentinel, str) and sentinel == "":
        return '`""`'
    return f"`{sentinel!r}`"


def generate_markdown_table() -> str:
    lines: list[str] = []
    lines.append("# Environment Variable Reference\n")
    lines.append(
        "All variables use the `AION_` prefix.  "
        "Generated from `src/settings.py` by `scripts/generate-env-docs.py`.\n"
    )
    lines.append(
        "| Variable | Type | Default | Description |"
    )
    lines.append(
        "|---|---|---|---|"
    )

    try:
        fields = AionSettings.model_fields  # pydantic v2
    except AttributeError:
        fields = AionSettings.__fields__  # pydantic v1

    prefix = (
        AionSettings.model_config.get("env_prefix", "AION_")
        if hasattr(AionSettings, "model_config")
        else "AION_"
    )

    for field_name, field_info in fields.items():
        env_var = f"{prefix}{field_name.upper()}"
        # Derive type from annotation
        try:
            annotation = AionSettings.__annotations__.get(field_name)
        except Exception:
            annotation = None
        type_str = _type_name(annotation)
        default_str = _field_default(field_info)
        description = ""
        if hasattr(field_info, "description") and field_info.description:
            description = field_info.description.replace("|", "\\|")
        elif hasattr(field_info, "field_info"):
            fi = field_info.field_info
            if hasattr(fi, "description") and fi.description:
                description = fi.description.replace("|", "\\|")
        lines.append(f"| `{env_var}` | {type_str} | {default_str} | {description} |")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(generate_markdown_table())
