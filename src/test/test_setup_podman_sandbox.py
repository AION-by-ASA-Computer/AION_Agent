"""Tests for Podman sandbox setup helper."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.setup_podman_sandbox import (
    ENV_BLOCK_HEADER,
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


def test_build_env_values_ghcr_image_without_host_src(tmp_path):
    values = _build_env_values(
        tmp_path, image="ghcr.io/x/aion-sandbox:1.2.3", host_src=False
    )
    assert values["AION_SANDBOX_CONTAINER_IMAGE"] == "ghcr.io/x/aion-sandbox:1.2.3"
    assert values["AION_SANDBOX_MOUNT_HOST_SRC"] == "0"


def test_target_user_is_sudo_caller_not_root(monkeypatch):
    import pwd

    import scripts.setup_podman_sandbox as mod

    me = pwd.getpwuid(os.getuid())
    monkeypatch.setattr(mod.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_USER", me.pw_name)
    user = mod._target_user()
    assert (user.name, user.uid, user.gid) == (me.pw_name, me.pw_uid, me.pw_gid)
    assert mod._podman_socket_path() == Path(
        f"/run/user/{me.pw_uid}/podman/podman.sock"
    )


def test_as_target_resets_primary_group_after_newgrp(monkeypatch):
    """Shell with 'newgrp docker' active: podman must not inherit that gid."""
    import scripts.setup_podman_sandbox as mod

    user = mod._target_user()
    monkeypatch.setattr(mod.os, "getgid", lambda: user.gid + 12345)
    argv = mod._as_target(["podman", "info"])
    assert argv[:5] == ["sudo", "-u", user.name, "-g", f"#{user.gid}"]
    assert argv[-2:] == ["podman", "info"]


def test_as_target_runs_directly_with_matching_ids():
    import scripts.setup_podman_sandbox as mod

    argv = mod._as_target(["podman", "info"])
    assert argv[0] == "env"
    assert any(a.startswith("XDG_RUNTIME_DIR=/run/user/") for a in argv)
