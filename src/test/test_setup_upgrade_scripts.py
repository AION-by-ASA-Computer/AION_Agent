"""Anti-regression tests for setup/upgrade orchestration scripts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _load_script_module(name: str, rel_path: str):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def upgrade_lib():
    return _load_script_module("aion_upgrade_lib", "scripts/upgrade_lib.py")


@pytest.fixture
def upgrade_runner():
    return _load_script_module("aion_upgrade_runner", "scripts/upgrade_runner.py")


REQUIRED_ORCHESTRATION = [
    "scripts/setup_core.py",
    "scripts/setup_aion_env.py",
    "scripts/upgrade_core.py",
    "scripts/upgrade_runner.py",
    "scripts/upgrade_lib.py",
    "scripts/upgrade-aion.sh",
    "scripts/setup-aion-env.sh",
    "scripts/sync_config.py",
    "scripts/sync_mcp_servers.py",
    "scripts/init_unified_db.py",
    "scripts/upgrades/README.md",
    "version.json",
]


def test_required_setup_upgrade_files_exist():
    missing = [p for p in REQUIRED_ORCHESTRATION if not (ROOT / p).is_file()]
    assert not missing, f"Missing orchestration files: {missing}"


def test_version_json_readable():
    data = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    assert isinstance(data.get("version"), str) and data["version"].strip()


def test_upgrade_lib_env_helpers(tmp_path, upgrade_lib):
    env = tmp_path / ".env"
    env.write_text("# comment\nAION_FOO=1\n", encoding="utf-8")

    assert upgrade_lib.ensure_env_key(env, "AION_FOO", "9") is True
    assert "AION_FOO=1" in env.read_text(encoding="utf-8")

    assert upgrade_lib.ensure_env_key(env, "AION_BAR", "0") is True
    assert "AION_BAR=0" in env.read_text(encoding="utf-8")

    assert upgrade_lib.rewrite_env_key(env, "AION_FOO", "2") is True
    assert "AION_FOO=2" in env.read_text(encoding="utf-8")

    assert upgrade_lib.rename_env_key(env, "AION_FOO", "AION_BAZ") is True
    text = env.read_text(encoding="utf-8")
    assert "AION_BAZ=2" in text
    assert "AION_FOO=" not in text

    assert upgrade_lib.remove_env_key(env, "AION_BAR") is True
    assert "AION_BAR=" not in env.read_text(encoding="utf-8")


def test_upgrade_lib_lock_acquire_release(tmp_path, upgrade_lib):
    lock = tmp_path / "data" / ".upgrade.lock"
    with upgrade_lib.LockManager(lock, stale_sec=1, yes=True):
        assert lock.is_file()
        payload = json.loads(lock.read_text(encoding="utf-8"))
        assert payload.get("pid")
    assert not lock.exists()


def test_upgrade_runner_sync_dir_is_non_destructive(tmp_path, upgrade_runner):
    src = tmp_path / "config_std"
    dst = tmp_path / "config"
    src.mkdir()
    dst.mkdir()
    (src / "profiles" / "new.yaml").parent.mkdir(parents=True)
    (src / "profiles" / "new.yaml").write_text("name: new\n", encoding="utf-8")
    (dst / "profiles" / "custom.yaml").parent.mkdir(parents=True)
    (dst / "profiles" / "custom.yaml").write_text("name: custom\n", encoding="utf-8")

    upgrade_runner._sync_dir(src, dst, "test")

    assert (dst / "profiles" / "new.yaml").read_text(encoding="utf-8") == "name: new\n"
    assert (dst / "profiles" / "custom.yaml").read_text(
        encoding="utf-8"
    ) == "name: custom\n"

    (src / "profiles" / "custom.yaml").write_text(
        "name: overwritten\n", encoding="utf-8"
    )
    upgrade_runner._sync_dir(src, dst, "test")
    assert (dst / "profiles" / "custom.yaml").read_text(
        encoding="utf-8"
    ) == "name: custom\n"


def test_upgrade_runner_dry_run_updates_version(tmp_path, upgrade_runner, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("AION_VERSION=1.0.0\n", encoding="utf-8")
    monkeypatch.setattr(upgrade_runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        upgrade_runner,
        "_sync_dir",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        upgrade_runner,
        "_run_version_script",
        lambda *_a, **_k: None,
    )

    upgrade_runner._update_aion_version("1.5.2", dry_run=False)
    assert "AION_VERSION=1.5.2" in env.read_text(encoding="utf-8")


def test_setup_core_dry_run_non_interactive(tmp_path):
    env_out = tmp_path / ".env"
    env_out.write_text("AION_CHAT_PASSWORD_AUTH=0\n", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "setup_core.py"),
            "--non-interactive",
            "--dry-run",
            "--skip-promo-playwright",
            "--output",
            str(env_out),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_upgrade_core_dry_run():
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "upgrade_core.py"),
            "--dry-run",
            "--skip-backup",
            "--skip-promo-playwright",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "UPGRADE SUMMARY" in proc.stdout


def test_shell_wrappers_dry_run():
    for script in ("scripts/setup-aion-env.sh", "scripts/upgrade-aion.sh"):
        proc = subprocess.run(
            ["bash", str(ROOT / script), "--dry-run"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert proc.returncode == 0, f"{script} failed:\n{proc.stderr}\n{proc.stdout}"
