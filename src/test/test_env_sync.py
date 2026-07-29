from __future__ import annotations

import json
import os

import pytest

from src.runtime.env_sync import (
    RUNTIME_ENV_NAME,
    META_NAME,
    apply_merged_env_to_os,
    diff_against_base,
    load_merged_env,
    reconcile_runtime_env,
    write_admin_overrides,
    write_env_file,
)


def _write_dotenv(path, mapping):
    lines = [f"{k}={v}" for k, v in mapping.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_reconcile_drops_redundant_runtime_keys(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    data.mkdir()

    _write_dotenv(repo / ".env", {"AION_MAX_AGENT_STEPS": "50", "AION_MODEL": "m1"})
    write_env_file(
        data / RUNTIME_ENV_NAME,
        {"AION_MAX_AGENT_STEPS": "50", "AION_MODEL": "m1", "AION_EXTRA": "x"},
    )

    monkeypatch.chdir(repo)
    report = reconcile_runtime_env(repo_root=repo, data_dir=data)

    runtime = (data / RUNTIME_ENV_NAME).read_text(encoding="utf-8")
    assert "AION_MAX_AGENT_STEPS" not in runtime
    assert "AION_MODEL" not in runtime
    assert "AION_EXTRA=x" in runtime
    assert report["runtime_keys_after"] == 1


def test_dotenv_change_drops_stale_legacy_override(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    data.mkdir()

    _write_dotenv(repo / ".env", {"AION_MAX_AGENT_STEPS": "50"})
    write_env_file(data / RUNTIME_ENV_NAME, {"AION_MAX_AGENT_STEPS": "15"})
    meta = {
        "migrated": True,
        "overrides": {
            "AION_MAX_AGENT_STEPS": {"source": "legacy", "updated_at": "t0"},
        },
    }
    (data / META_NAME).write_text(json.dumps(meta), encoding="utf-8")

    reconcile_runtime_env(repo_root=repo, data_dir=data)
    runtime = (data / RUNTIME_ENV_NAME).read_text(encoding="utf-8")
    assert "AION_MAX_AGENT_STEPS" not in runtime


def test_admin_override_is_preserved_when_dotenv_differs(tmp_path):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    data.mkdir()

    _write_dotenv(repo / ".env", {"AION_MAX_AGENT_STEPS": "15"})
    write_admin_overrides(
        {"AION_MAX_AGENT_STEPS": "50"},
        data_dir=data,
        repo_root=repo,
    )

    merged = load_merged_env(repo_root=repo, data_dir=data)
    assert merged["AION_MAX_AGENT_STEPS"] == "50"

    _write_dotenv(repo / ".env", {"AION_MAX_AGENT_STEPS": "99"})
    reconcile_runtime_env(repo_root=repo, data_dir=data)
    merged = load_merged_env(repo_root=repo, data_dir=data)
    assert merged["AION_MAX_AGENT_STEPS"] == "50"


def test_diff_against_base_only_returns_changed_keys(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_dotenv(
        repo / ".env",
        {"AION_MAX_AGENT_STEPS": "50", "AION_MODEL": "m1"},
    )

    diff = diff_against_base(
        {"AION_MAX_AGENT_STEPS": "50", "AION_MODEL": "m2"},
        repo_root=repo,
    )
    assert diff == {"AION_MODEL": "m2"}


def test_apply_merged_env_to_os(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    data.mkdir()

    _write_dotenv(repo / ".env", {"AION_MAX_AGENT_STEPS": "50"})
    write_admin_overrides(
        {"AION_MAX_AGENT_STEPS": "60"},
        data_dir=data,
        repo_root=repo,
    )

    monkeypatch.delenv("AION_MAX_AGENT_STEPS", raising=False)
    apply_merged_env_to_os(repo_root=repo, data_dir=data)
    assert os.environ["AION_MAX_AGENT_STEPS"] == "60"


def test_apply_merged_env_respects_process_env_for_base(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    data.mkdir()

    _write_dotenv(repo / ".env", {"AION_CHAT_PASSWORD_AUTH": "1"})
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "0")
    apply_merged_env_to_os(repo_root=repo, data_dir=data)
    assert os.environ["AION_CHAT_PASSWORD_AUTH"] == "0"


def test_apply_merged_env_runtime_overrides_process_env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    data.mkdir()

    _write_dotenv(repo / ".env", {"AION_CHAT_PASSWORD_AUTH": "0"})
    write_admin_overrides(
        {"AION_CHAT_PASSWORD_AUTH": "1"},
        data_dir=data,
        repo_root=repo,
    )
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "0")
    apply_merged_env_to_os(repo_root=repo, data_dir=data)
    assert os.environ["AION_CHAT_PASSWORD_AUTH"] == "1"


def test_first_setup_complete_preserved_on_reconcile(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    data.mkdir()

    _write_dotenv(repo / ".env", {"AION_FIRST_SETUP_COMPLETE": "0"})
    write_env_file(data / RUNTIME_ENV_NAME, {"AION_FIRST_SETUP_COMPLETE": "1"})
    meta = {
        "migrated": True,
        "overrides": {
            "AION_FIRST_SETUP_COMPLETE": {"source": "legacy", "updated_at": "t0"},
        },
    }
    (data / META_NAME).write_text(json.dumps(meta), encoding="utf-8")

    reconcile_runtime_env(repo_root=repo, data_dir=data)
    merged = load_merged_env(repo_root=repo, data_dir=data)
    assert merged["AION_FIRST_SETUP_COMPLETE"] == "1"


def test_first_setup_complete_not_cleared_by_unrelated_admin_save(tmp_path):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    repo.mkdir()
    data.mkdir()

    _write_dotenv(
        repo / ".env",
        {"AION_FIRST_SETUP_COMPLETE": "0", "AION_MAX_AGENT_STEPS": "50"},
    )
    write_admin_overrides(
        {"AION_FIRST_SETUP_COMPLETE": "1"},
        data_dir=data,
        repo_root=repo,
    )

    write_admin_overrides(
        {"AION_MAX_AGENT_STEPS": "60"},
        data_dir=data,
        repo_root=repo,
    )

    merged = load_merged_env(repo_root=repo, data_dir=data)
    assert merged["AION_FIRST_SETUP_COMPLETE"] == "1"
    assert merged["AION_MAX_AGENT_STEPS"] == "60"
