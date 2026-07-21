"""Session venv bootstrap for office skill Python dependencies."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.tools import session_venv


def test_venv_create_argv_uses_system_site_packages_in_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AION_SANDBOX_IN_CONTAINER", "1")
    argv = session_venv._venv_create_argv(Path("/session/.venv"))
    assert argv == [
        session_venv.sys.executable,
        "-m",
        "venv",
        "--system-site-packages",
        "/session/.venv",
    ]


def test_venv_create_argv_plain_on_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AION_SANDBOX_IN_CONTAINER", raising=False)
    argv = session_venv._venv_create_argv(Path("/data/sessions/x/.venv"))
    assert argv == [session_venv.sys.executable, "-m", "venv", "/data/sessions/x/.venv"]


def test_bootstrap_skills_skipped_when_marker_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vdir = tmp_path / ".venv"
    vdir.mkdir()
    (vdir / ".aion_skills_bootstrapped").write_text("ok\n", encoding="utf-8")
    called = False

    def _fail(*_a, **_k):
        nonlocal called
        called = True
        raise AssertionError("bootstrap should not run when marker exists")

    monkeypatch.setattr(session_venv, "run_session_subprocess", _fail)
    session_venv._bootstrap_session_venv_skills("sess", vdir)
    assert called is False


def test_bootstrap_skills_runs_in_container_when_unmarked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AION_SANDBOX_IN_CONTAINER", "1")
    session = tmp_path / "sess"
    vdir = session / ".venv"
    vbin = vdir / "bin"
    vbin.mkdir(parents=True)
    vpy = vbin / "python"
    vpy.write_text("#!/bin/sh\n", encoding="utf-8")

    req = tmp_path / "requirements-sandbox-skills.txt"
    req.write_text("defusedxml\n", encoding="utf-8")
    monkeypatch.setattr(session_venv, "_skills_requirements_path", lambda: req)
    monkeypatch.setattr(session_venv, "session_root", lambda sid: session)
    monkeypatch.setattr(session_venv, "session_venv_python", lambda sid: vpy)

    captured: dict = {}

    def _fake_run(session_id, argv, **kwargs):
        captured["argv"] = list(argv)
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "ok"
        proc.stderr = ""
        return proc

    monkeypatch.setattr(session_venv, "run_session_subprocess", _fake_run)
    monkeypatch.setenv("AION_SANDBOX_PIP_USE_UV", "0")

    session_venv._bootstrap_session_venv_skills("sess", vdir)

    assert captured["argv"][:4] == [str(vpy), "-m", "pip", "install"]
    assert (vdir / ".aion_skills_bootstrapped").is_file()


def test_bootstrap_skills_runs_pip_on_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("AION_SANDBOX_IN_CONTAINER", raising=False)
    session = tmp_path / "sess"
    vdir = session / ".venv"
    vbin = vdir / "bin"
    vbin.mkdir(parents=True)
    vpy = vbin / "python"
    vpy.write_text("#!/bin/sh\n", encoding="utf-8")

    req = tmp_path / "requirements-sandbox-skills.txt"
    req.write_text("defusedxml\n", encoding="utf-8")
    monkeypatch.setattr(session_venv, "_skills_requirements_path", lambda: req)
    monkeypatch.setattr(session_venv, "session_root", lambda sid: session)
    monkeypatch.setattr(session_venv, "session_venv_python", lambda sid: vpy)

    captured: dict = {}

    def _fake_run(session_id, argv, **kwargs):
        captured["argv"] = list(argv)
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "ok"
        proc.stderr = ""
        return proc

    monkeypatch.setattr(session_venv, "run_session_subprocess", _fake_run)
    monkeypatch.setenv("AION_SANDBOX_PIP_USE_UV", "0")

    session_venv._bootstrap_session_venv_skills("sess", vdir)

    assert captured["argv"][:4] == [str(vpy), "-m", "pip", "install"]
    assert captured["argv"][-2:] == ["-r", str(req)]
    assert (vdir / ".aion_skills_bootstrapped").is_file()
