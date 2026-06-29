"""Tests for Podman sandbox setup helper."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.setup_podman_sandbox import (
    ENV_BLOCK_HEADER,
    ENV_KEYS,
    _build_env_values,
    _merge_env_file,
)


def test_build_env_values_uses_repo_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    values = _build_env_values(tmp_path)
    assert values["AION_SANDBOX_BACKEND"] == "container"
    assert values["AION_SANDBOX_HOST_DATA_DIR"] == str((tmp_path / "data").resolve())
    assert values["AION_SANDBOX_HOST_UID"] == str(os.getuid())


def test_merge_env_file_inserts_block(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=bar\n", encoding="utf-8")
    values = _build_env_values(tmp_path)
    _merge_env_file(env, values, dry_run=False)
    text = env.read_text(encoding="utf-8")
    assert ENV_BLOCK_HEADER in text
    assert "AION_SANDBOX_BACKEND=container" in text
    assert "FOO=bar" in text
    assert text.count("AION_SANDBOX_BACKEND=") == 1
