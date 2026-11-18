"""Variables of custom MCP servers never steer the container CLI (security review #1, #2).

Covers: server variables travel in a private --env-file (not in the docker/podman
CLI environment), multi-line values go by name except CLI settings, the jail's own
AION_JAIL_* variables cannot be overridden, reserved names are refused on admin
edits and dropped at spawn, and the backend PATH never reaches the jail.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import src.aion_env  # noqa: F401
from src.mcp_custom.manifest import env_key_error
from src.security import container_runtime as cr
from src.security.container_policy import build_custom_mcp_run_argv


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Docker runtime with env files written under tmp_path and no deletion timer."""
    monkeypatch.setenv("AION_CONTAINER_RUNTIME", "docker")
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(cr, "_env_file_dir", lambda: tmp_path)
    monkeypatch.setattr(cr, "_remove_later", lambda *_a, **_k: None)
    monkeypatch.setattr(cr, "resolve_custom_mcp_host_path", lambda p: Path(p))
    rt = cr.ContainerRuntime()
    rt.socket = ""
    return rt


def _env_file_values(path: str) -> dict:
    return dict(
        line.split("=", 1)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
    )


def test_manifest_docker_host_cannot_redirect_the_cli(runtime, tmp_path: Path):
    """DOCKER_HOST and secrets from the server go to the env file, never to the CLI env."""
    cmd, args, spawn_env = runtime.build_custom_mcp_spawn(
        "evil_srv",
        server_path=tmp_path / "srv",
        env={"DOCKER_HOST": "tcp://attacker:2375", "API_TOKEN": "s3cret"},
    )
    assert spawn_env.get("DOCKER_HOST") != "tcp://attacker:2375"
    assert "API_TOKEN" not in spawn_env
    env_file = args[args.index("--env-file") + 1]
    values = _env_file_values(env_file)
    assert values == {"DOCKER_HOST": "tcp://attacker:2375", "API_TOKEN": "s3cret"}
    assert not any("s3cret" in a for a in args)  # never on the command line
    if os.name != "nt":
        assert oct(Path(env_file).stat().st_mode & 0o777) == "0o600"


def test_multiline_values_go_by_name_except_cli_settings(runtime, tmp_path: Path):
    """A PEM key is passed by name; a multi-line CLI setting is dropped, not forwarded."""
    pem = "-----BEGIN KEY-----\nabc\n-----END KEY-----"
    _cmd, args, spawn_env = runtime.build_custom_mcp_spawn(
        "pem_srv",
        server_path=tmp_path / "srv",
        env={"SERVICE_KEY": pem, "HTTPS_PROXY": "http://x\nhttp://y", "PLAIN": "1"},
    )
    assert (
        args[args.index("SERVICE_KEY") - 1] == "-e" and spawn_env["SERVICE_KEY"] == pem
    )
    assert "HTTPS_PROXY" not in args
    assert spawn_env.get("HTTPS_PROXY") != "http://x\nhttp://y"
    assert _env_file_values(args[args.index("--env-file") + 1]) == {"PLAIN": "1"}


def test_jail_variables_come_last():
    """A server variable named AION_JAIL_UID is not forwarded and the jail's own -e wins."""
    import ipaddress

    from src.mcp_custom.egress import ResolvedEgress

    argv = build_custom_mcp_run_argv(
        runtime="docker",
        image="aion/sandbox:latest",
        slug="s",
        host_server_dir=Path("/h/s"),
        env={"AION_JAIL_UID": "0"},
        env_file=Path("/tmp/x.env"),
        egress=ResolvedEgress(rules=[(ipaddress.ip_network("10.0.0.1/32"), ())]),
    )
    assert "AION_JAIL_UID" not in argv
    assert argv.index("--env-file") < argv.index("AION_JAIL_UID=65534")


@pytest.mark.parametrize(
    "key", ["PATH", "LD_PRELOAD", "PYTHONPATH", "AION_JAIL_UID", "HOME"]
)
def test_reserved_names_are_refused(key: str):
    """The single name rule refuses what would change how the jail starts."""
    assert env_key_error(key)


@pytest.mark.parametrize(
    "key", ["DOCKER_HOST", "HTTPS_PROXY", "SSL_CERT_FILE", "CRM_API_KEY"]
)
def test_legit_names_stay_allowed(key: str):
    """Names that are harmless inside the container are not blocked."""
    assert env_key_error(key) is None


def test_spawn_drops_reserved_registry_env(monkeypatch: pytest.MonkeyPatch):
    """A hand-edited (or admin-edited) registry env with LD_PRELOAD/PATH never reaches the jail."""
    from src.mcp_custom import runtime as rt
    from src.mcp_manager import mcp_manager

    cfg = {
        "env": {"LD_PRELOAD": "/deps/x.so", "PATH": "/evil", "CRM_URL": "https://crm"},
        "aion_custom": {},
    }
    monkeypatch.setattr(mcp_manager, "_registry", {"srv": cfg})
    assert rt._literal_env("srv", set(), cfg) == {"CRM_URL": "https://crm"}


def test_jail_env_has_no_backend_path():
    """In the container PATH comes from the image, not from the backend."""
    from src.mcp_custom.runtime import finalize_process_env

    out = finalize_process_env(
        {"PATH": r"C:\Windows;C:\Python"}, in_container=True, deps_dir=None
    )
    assert "PATH" not in out


def test_admin_edit_with_reserved_name_is_refused(monkeypatch: pytest.MonkeyPatch):
    """PUT /admin/mcp/{name} on a custom server rejects LD_PRELOAD with 422."""
    import asyncio

    from fastapi import HTTPException

    from src.api import admin
    from src.mcp_manager import mcp_manager

    cfg = {
        "command": "python",
        "env": {},
        "aion_custom": {"credential_mode": "none", "credential_schema": []},
    }
    monkeypatch.setattr(mcp_manager, "_registry", {"srv": cfg})
    with pytest.raises(HTTPException) as err:
        asyncio.run(
            admin.update_mcp_config(
                "srv", admin.MCPUpdate(env={"LD_PRELOAD": "/deps/x.so"})
            )
        )
    assert err.value.status_code == 422


def test_env_file_name_ignores_the_slug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A slug like '../x' cannot place the env file outside its private folder."""
    monkeypatch.setattr(cr, "_env_file_dir", lambda: tmp_path)
    monkeypatch.setattr(cr, "_remove_later", lambda *_a, **_k: None)
    path, _ = cr.write_jail_env_file("../../escape", {"A": "1"})
    assert path is not None and path.parent == tmp_path and path.name.startswith("jail-")
