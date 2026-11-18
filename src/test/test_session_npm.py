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


def _fake_session(tmp_path, monkeypatch):
    """Point session_root() at tmp_path so tests can lay out workspace/node_modules."""
    from src.tools import session_npm

    monkeypatch.setattr(session_npm, "session_root", lambda _sid: tmp_path)
    return session_npm


def _add_pkg(base, name):
    (base / name).mkdir(parents=True)
    (base / name / "package.json").write_text("{}", encoding="utf-8")


def test_session_installed_packages_skip_npm_install(tmp_path, monkeypatch):
    """A package installed by an earlier call in the same session is not reinstalled."""
    session_npm = _fake_session(tmp_path, monkeypatch)
    monkeypatch.delenv("NODE_PATH", raising=False)
    _add_pkg(tmp_path / "workspace" / "node_modules", "lodash")
    monkeypatch.setattr(
        session_npm, "workspace_dir", lambda _sid: pytest.fail("npm install ran")
    )

    assert session_npm.is_installed_in_session("sid", "lodash")
    out = session_npm.install_npm_packages("sid", ["lodash"])
    assert out.startswith("OK:") and "already installed in this session" in out


def test_is_installed_in_session_is_read_only(tmp_path, monkeypatch):
    """Checking a session without a workspace must not create any folder."""
    session_npm = _fake_session(tmp_path, monkeypatch)
    assert not session_npm.is_installed_in_session("sid", "docx")
    assert not (tmp_path / "workspace").exists()


def test_build_session_env_forwards_node_path_with_custom_allowlist(
    tmp_path, monkeypatch
):
    """NODE_PATH reaches the sandbox even when AION_SANDBOX_ENV_ALLOWLIST omits it.

    Regression: the allowlist shipped in .env.example dropped NODE_PATH, so
    require("docx") failed although docx was preinstalled in the image.
    """
    from src.security.session_env import build_session_env

    monkeypatch.setenv("NODE_PATH", "/usr/lib/node_modules")
    monkeypatch.setenv("AION_SANDBOX_ENV_ALLOWLIST", "LANG,PATH,HOME")
    env = build_session_env("test-session", session_root=tmp_path)
    assert env.get("NODE_PATH") == "/usr/lib/node_modules"


def test_missing_module_hint_cases(tmp_path, monkeypatch):
    """The hint after a failed node run depends on why the module was missing."""
    session_npm = _fake_session(tmp_path, monkeypatch)
    glob = tmp_path / "global"
    _add_pkg(glob, "docx")
    monkeypatch.setenv("NODE_PATH", str(glob))

    cjs = "Error: Cannot find module 'docx'\nRequire stack:\n- /x/workspace/a.js"
    esm = (
        "Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'docx' imported from "
        "/x/workspace/a.mjs"
    )
    missing = "Error: Cannot find module 'lodash/fp'"
    local = "Error: Cannot find module './data.json'"

    # Installed but loaded with ESM import -> switch to require, no reinstall.
    h = session_npm.missing_module_hint("sid", esm)
    assert 'require("docx")' in h and "Do NOT call sandbox_install_npm_packages" in h
    # Installed, CommonJS, still not found -> environment issue, python-docx fallback.
    h = session_npm.missing_module_hint("sid", cjs)
    assert "python-docx" in h and "do NOT call" in h
    # Really missing -> install the bare package name (subpath stripped).
    h = session_npm.missing_module_hint("sid", missing)
    assert 'packages=["lodash"]' in h
    # Agent's own relative file -> path hint, not an install.
    h = session_npm.missing_module_hint("sid", local)
    assert "sandbox_install_npm_packages" not in h and "./data.json" in h
    # Unrelated failure -> no hint.
    assert session_npm.missing_module_hint("sid", "SyntaxError: Unexpected token") == ""
