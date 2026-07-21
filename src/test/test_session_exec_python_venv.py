"""sandbox_exec_allowlisted must use the session venv for python (same as run_python_file)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.security.session_env import build_exec_env, build_session_env
from src.tools.session_exec import run_allowlisted


def test_build_session_env_prepends_venv_bin_to_path(tmp_path: Path) -> None:
    vdir = tmp_path / ".venv"
    vbin = vdir / "bin"
    vbin.mkdir(parents=True)
    (vbin / "python").write_text("#!/bin/sh\necho session\n", encoding="utf-8")

    env = build_session_env(
        "sess-1",
        session_root=tmp_path,
        venv_dir=vdir,
    )
    path_parts = env["PATH"].split(os.pathsep)
    assert path_parts[0] == str(vbin.resolve())
    assert env["VIRTUAL_ENV"] == str(vdir.resolve())


def test_build_exec_env_auto_detects_session_venv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.tools.session_venv.session_root",
        lambda sid: tmp_path,
    )
    vdir = tmp_path / ".venv"
    vbin = vdir / "bin"
    vbin.mkdir(parents=True)

    env = build_exec_env(
        "sess-1",
        session_root=tmp_path,
        argv=["python", "scripts/office/unpack.py"],
    )
    assert env["VIRTUAL_ENV"] == str(vdir.resolve())
    path_parts = env["PATH"].split(os.pathsep)
    assert str(vbin.resolve()) in path_parts
    assert path_parts.index(str(vbin.resolve())) <= 2


def test_run_allowlisted_python_uses_session_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = tmp_path / "sess"
    session.mkdir()
    scripts = session / "scripts" / "office"
    scripts.mkdir(parents=True)
    (scripts / "unpack.py").write_text("print('ok')\n", encoding="utf-8")

    vdir = session / ".venv" / "bin"
    vdir.mkdir(parents=True)
    session_py = vdir / "python"
    session_py.write_text("#!/bin/sh\n", encoding="utf-8")
    session_py.chmod(0o755)

    global_py = tmp_path / "opt-venv-bin"
    global_py.mkdir()
    (global_py / "python").write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr("src.tools.session_exec.session_root", lambda sid: session)
    monkeypatch.setattr("src.tools.session_venv.session_root", lambda sid: session)
    monkeypatch.setattr("src.session_workspace.session_root", lambda sid: session)

    class _Policy:
        @staticmethod
        def exec_is_enabled():
            return True

        @staticmethod
        def get_exec_allowlist():
            return [
                {
                    "executable": "python",
                    "argv_prefix": [],
                    "validate_path_positions": [1, 2],
                }
            ]

    monkeypatch.setattr("src.tools.session_exec.get_policy", lambda: _Policy())

    captured: dict = {}

    def _fake_run(session_id, argv, **kwargs):
        captured["argv"] = list(argv)
        captured["env"] = kwargs.get("env", {})

        class _Proc:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return _Proc()

    monkeypatch.setattr("src.tools.session_exec.run_session_subprocess", _fake_run)
    monkeypatch.setenv("PATH", f"{global_py}{os.pathsep}/usr/bin")
    monkeypatch.setenv("AION_SANDBOX_AUTO_VENV", "0")

    result = run_allowlisted(
        "sess-1",
        [
            "python",
            "scripts/office/unpack.py",
            "uploads/doc.docx",
            "workspace/unpacked/",
        ],
    )

    assert result["ok"] is True
    assert captured["argv"][0] == str(session_py.resolve())
    assert captured["env"]["VIRTUAL_ENV"] == str((session / ".venv").resolve())
