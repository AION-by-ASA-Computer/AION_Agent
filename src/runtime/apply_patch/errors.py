"""OpenCode-style apply_patch format errors."""

from __future__ import annotations


class PatchParseError(ValueError):
    pass


class PatchApplyError(ValueError):
    pass
