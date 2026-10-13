"""Tests for Podman sandbox setup helper."""

from __future__ import annotations

import os

from scripts.setup_podman_sandbox import (
    ENV_BLOCK_HEADER,
    _build_env_values,
    _is_registry_image,
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


def test_build_env_values_custom_image(tmp_path):
    image = "ghcr.io/aion-by-asa-computer/aion-sandbox:1.6.1"
    values = _build_env_values(tmp_path, image)
    assert values["AION_SANDBOX_CONTAINER_IMAGE"] == image
    assert values["AION_SANDBOX_LIVE_SRC"] == "0"
    assert _build_env_values(tmp_path)["AION_SANDBOX_LIVE_SRC"] == "1"


def test_is_registry_image():
    assert _is_registry_image("ghcr.io/aion-by-asa-computer/aion-sandbox:1.6.1")
    assert _is_registry_image("registry.local:5000/aion/sandbox:latest")
    assert not _is_registry_image("aion/sandbox:latest")
    assert not _is_registry_image("localhost/aion/sandbox:latest")
    assert not _is_registry_image("sandbox:latest")


def test_build_env_values_userns(tmp_path):
    assert _build_env_values(tmp_path)["AION_SANDBOX_CONTAINER_USERNS"] == "keep-id"
    values = _build_env_values(tmp_path, userns="root")
    assert values["AION_SANDBOX_CONTAINER_USERNS"] == "root"
