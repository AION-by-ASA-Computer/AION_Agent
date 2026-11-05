"""session_npm validation."""

from __future__ import annotations

import pytest

from src.tools.session_npm import _validate_package_names


def test_validate_package_names_accepts_docx():
    assert _validate_package_names(["docx"]) == ["docx"]


def test_validate_package_names_rejects_shell():
    with pytest.raises(ValueError):
        _validate_package_names(["docx; rm -rf /"])


def test_preinstalled_packages_skip_npm_install(tmp_path, monkeypatch):
    """Libraries baked into the Docker image (NODE_PATH) need no workspace install."""
    import os

    from src.tools import session_npm

    (tmp_path / "docx").mkdir()
    (tmp_path / "docx" / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(
        "NODE_PATH", os.pathsep.join([str(tmp_path / "missing"), str(tmp_path)])
    )
    # Would fail if npm were invoked: the session workspace must stay untouched.
    monkeypatch.setattr(
        session_npm, "workspace_dir", lambda _sid: pytest.fail("npm install ran")
    )

    assert session_npm.is_preinstalled("docx")
    assert not session_npm.is_preinstalled("pptxgenjs")
    out = session_npm.install_npm_packages("sid", ["docx"])
    assert out.startswith("OK:") and "already preinstalled" in out


def test_missing_packages_still_go_through_npm(tmp_path, monkeypatch):
    """Only the packages not preinstalled are handed to npm."""
    from src.tools import session_npm

    (tmp_path / "docx").mkdir()
    (tmp_path / "docx" / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NODE_PATH", str(tmp_path))
    monkeypatch.setattr(
        session_npm.shutil, "which", lambda _exe: None
    )  # stop before running npm
    out = session_npm.install_npm_packages("sid", ["docx", "lodash"])
    assert out.startswith("Error: npm not found")


def test_build_session_env_has_npm_config_cache(tmp_path):
    from src.security.session_env import build_session_env

    env = build_session_env("test-session", session_root=tmp_path)
    assert env.get("NPM_CONFIG_CACHE") == "/tmp/.npm-cache"


def test_link_container_parent_site_packages(tmp_path, monkeypatch):
    from src.tools.session_venv import _link_container_parent_site_packages

    # Fake /opt/venv/lib/python3.13/site-packages
    fake_opt = tmp_path / "opt_venv"
    fake_opt_site = fake_opt / "lib" / "python3.13" / "site-packages"
    fake_opt_site.mkdir(parents=True)

    # Fake session venv lib/python3.13/site-packages
    fake_session_venv = tmp_path / "session_venv"
    fake_session_site = fake_session_venv / "lib" / "python3.13" / "site-packages"
    fake_session_site.mkdir(parents=True)

    from pathlib import Path

    monkeypatch.setattr(
        "src.tools.session_venv.Path",
        lambda p: (fake_opt / "lib") if p == "/opt/venv/lib" else Path(p),
    )

    _link_container_parent_site_packages(fake_session_venv)

    pth_file = fake_session_site / "parent_opt_venv.pth"
    assert pth_file.is_file()
    assert str(fake_opt_site.resolve()) in pth_file.read_text(encoding="utf-8")
