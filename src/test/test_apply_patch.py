"""Tests for OpenCode-style apply_patch port."""

import pytest
from pathlib import Path

from src.runtime.apply_patch import PatchApplyError, apply_patch_text, parse_patch


def test_parse_add_update_delete():
    patch = """*** Begin Patch
*** Add File: nested/new.txt
+created
*** Delete File: delete.txt
*** Update File: modify.txt
@@
-line2
+changed
*** End Patch"""
    hunks = parse_patch(patch)
    assert len(hunks) == 3


def test_apply_patch_roundtrip(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "modify.txt").write_text("line1\nline2\n", encoding="utf-8")
    (ws / "delete.txt").write_text("obsolete\n", encoding="utf-8")

    patch = """*** Begin Patch
*** Add File: nested/new.txt
+created
*** Delete File: delete.txt
*** Update File: modify.txt
@@
-line2
+changed
*** End Patch"""
    result = apply_patch_text(tmp_path, patch)
    assert "nested/new.txt" in result.summary
    assert (ws / "nested" / "new.txt").read_text(encoding="utf-8") == "created\n"
    assert not (ws / "delete.txt").exists()
    assert "changed" in (ws / "modify.txt").read_text(encoding="utf-8")


def test_empty_patch_rejected(tmp_path: Path):
    with pytest.raises(PatchApplyError, match="empty patch"):
        apply_patch_text(tmp_path, "*** Begin Patch\n*** End Patch")


def test_invalid_patch_rejected(tmp_path: Path):
    with pytest.raises(PatchApplyError, match="verification failed"):
        apply_patch_text(tmp_path, "not a patch")
