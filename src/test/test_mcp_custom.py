"""Unit and integration tests for customer-built MCP servers (src/mcp_custom)."""

from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest

import src.aion_env  # noqa: F401
from src.mcp_custom.manifest import (
    Manifest,
    ManifestError,
    parse_manifest_data,
    parse_manifest_text,
)
from src.mcp_custom.paths import is_custom_config, slug_conflict, slug_format_error
from src.mcp_custom.package import stage_upload
from src.mcp_custom.runtime import (
    CustomMcpUnavailable,
    ensure_can_start,
    prepare_custom_spawn,
)
from src.security.container_policy import (
    build_custom_mcp_run_argv,
    container_name_for_custom_mcp,
    is_docker_runtime,
)


@pytest.fixture(autouse=True)
def isolated_custom_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "custom"
    root.mkdir(parents=True, exist_ok=True)
    (root / ".staging").mkdir(parents=True, exist_ok=True)
    (root / ".versions").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("src.mcp_custom.paths.custom_root", lambda: root)
    monkeypatch.setattr("src.mcp_custom.package.staging_root", lambda: root / ".staging")
    monkeypatch.setattr("src.mcp_custom.install.custom_root", lambda: root)
    monkeypatch.setattr("src.mcp_custom.install.versions_root", lambda: root / ".versions")
    local_reg = tmp_path / "mcp_registry.local.yaml"
    local_reg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.mcp_manager.mcp_manager.local_registry_path", str(local_reg))
    from src.mcp_manager import mcp_manager
    mcp_manager._registry_local = {}
    mcp_manager._rebuild_merged()


# ─────────────────────────────────────────────────────────────
# 1. Manifest tests
# ─────────────────────────────────────────────────────────────

def test_manifest_valid_python():
    data = {
        "aion_mcp": 1,
        "slug": "crm_custom",
        "name": "CRM Custom",
        "description": "Integration with custom CRM",
        "version": "1.0.0",
        "runtime": "python",
        "entrypoint": "server.py",
        "credentials": {
            "mode": "org_shared",
            "fields": [
                {"key": "CRM_API_KEY", "label": "API Key", "secret": True, "required": True}
            ],
        },
        "env": {"CRM_BASE_URL": "https://crm.local"},
    }
    m = parse_manifest_data(data)
    assert m.slug == "crm_custom"
    assert m.version == "1.0.0"
    assert m.credentials.mode == "org_shared"
    assert len(m.credentials.fields) == 1
    assert m.credentials.fields[0].key == "CRM_API_KEY"
    assert m.env["CRM_BASE_URL"] == "https://crm.local"

    schema = m.credential_schema()
    assert len(schema) == 1
    assert schema[0]["key"] == "CRM_API_KEY"
    assert schema[0]["is_secret"] is True
    assert m.secret_keys() == ["CRM_API_KEY"]


def test_manifest_rejects_unknown_fields():
    data = {
        "aion_mcp": 1,
        "slug": "crm_custom",
        "name": "CRM",
        "description": "desc",
        "version": "1.0.0",
        "unknown_extra_field": "bad",
    }
    with pytest.raises(ManifestError) as exc:
        parse_manifest_data(data)
    assert "unknown field" in str(exc.value)


def test_manifest_rejects_unsupported_runtime_in_v0():
    data = {
        "aion_mcp": 1,
        "slug": "node_mcp",
        "name": "Node MCP",
        "description": "desc",
        "version": "1.0.0",
        "runtime": "node",
    }
    with pytest.raises(ManifestError) as exc:
        parse_manifest_data(data)
    assert "planned for AION custom MCP v1" in str(exc.value)


def test_manifest_rejects_reserved_env_keys():
    for bad_key in ["PATH", "AION_DB_URL", "PYTHONPATH"]:
        data = {
            "aion_mcp": 1,
            "slug": "test_mcp",
            "name": "Test",
            "description": "desc",
            "version": "1.0.0",
            "env": {bad_key: "val"},
        }
        with pytest.raises(ManifestError) as exc:
            parse_manifest_data(data)
        assert "reserved" in str(exc.value)


def test_manifest_rejects_placeholders_in_env():
    data = {
        "aion_mcp": 1,
        "slug": "test_mcp",
        "name": "Test",
        "description": "desc",
        "version": "1.0.0",
        "env": {"TARGET": "${AION_CHAT_AUTH_SECRET}"},
    }
    with pytest.raises(ManifestError) as exc:
        parse_manifest_data(data)
    assert "placeholders" in str(exc.value)


def test_manifest_rejects_env_credentials_overlap():
    data = {
        "aion_mcp": 1,
        "slug": "test_mcp",
        "name": "Test",
        "description": "desc",
        "version": "1.0.0",
        "credentials": {
            "mode": "org_shared",
            "fields": [{"key": "SHARED_VAR", "label": "Shared", "secret": False}],
        },
        "env": {"SHARED_VAR": "val"},
    }
    with pytest.raises(ManifestError) as exc:
        parse_manifest_data(data)
    assert "keys declared both in env and credentials" in str(exc.value)


# ─────────────────────────────────────────────────────────────
# 2. Package & Zip staging tests
# ─────────────────────────────────────────────────────────────

def test_package_zip_slip_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.py", "print('hacked')")
    raw = buf.getvalue()

    staged = stage_upload("exploit.zip", raw, actor="tester")
    assert staged.status == "invalid"
    assert any("unsafe path" in err for err in staged.errors)


def test_package_single_py_needs_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("src.mcp_custom.paths.staging_root", lambda: tmp_path / "staging")
    code = """
import os
from fastmcp import FastMCP

mcp = FastMCP("demo")

@mcp.tool()
def hello() -> str:
    key = os.environ.get("DEMO_API_KEY")
    return f"key={key}"
"""
    staged = stage_upload("demo_server.py", code.encode("utf-8"), actor="tester")
    assert staged.status == "needs_manifest"
    assert staged.source_kind == "py"
    assert staged.suggested_slug == "demo_server"
    assert "DEMO_API_KEY" in staged.env_used


def test_package_valid_zip_with_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("src.mcp_custom.paths.staging_root", lambda: tmp_path / "staging")
    manifest_yaml = """
aion_mcp: 1
slug: sales_tool
name: Sales Tool
description: Sales integration
version: 1.0.0
runtime: python
entrypoint: server.py
credentials:
  mode: org_shared
  fields:
    - key: SALES_TOKEN
      label: Sales Token
      secret: true
      required: true
env:
  SALES_HOST: https://sales.example.com
"""
    server_py = """
import os
from fastmcp import FastMCP

mcp = FastMCP("sales")

@mcp.tool()
def get_status() -> str:
    token = os.environ.get("SALES_TOKEN")
    host = os.environ.get("SALES_HOST")
    return "ok"
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("aion-mcp.yaml", manifest_yaml)
        z.writestr("server.py", server_py)
    raw = buf.getvalue()

    staged = stage_upload("sales.zip", raw, actor="tester")
    # A valid package is verified in the jail (dependencies + probe) before it is "ready".
    assert staged.status == "verifying"
    assert staged.manifest is not None
    assert staged.manifest["slug"] == "sales_tool"
    assert "SALES_TOKEN" in staged.env_used
    assert "SALES_HOST" in staged.env_used


# ─────────────────────────────────────────────────────────────
# 3. Paths & Slugs
# ─────────────────────────────────────────────────────────────

def test_slug_validation():
    assert slug_format_error("crm") is None
    assert slug_format_error("my_custom_mcp_server") is None
    assert slug_format_error("bad-with-dash") is not None
    assert slug_format_error("UPPERCASE") is not None
    assert slug_format_error("1_starts_with_digit") is not None
    assert slug_format_error("x") is not None  # too short


def test_slug_conflict_with_std():
    # 'session_sandbox' is an AION built-in server
    conflict = slug_conflict("session_sandbox")
    assert conflict is not None
    assert "AION built-in server" in conflict


# ─────────────────────────────────────────────────────────────
# 4. Container Policy & Security Jail
# ─────────────────────────────────────────────────────────────

def test_is_docker_runtime():
    assert is_docker_runtime("docker") is True
    assert is_docker_runtime("docker.exe") is True
    assert is_docker_runtime("C:\\Program Files\\Docker\\docker.exe") is True
    assert is_docker_runtime("podman") is False
    assert is_docker_runtime("/usr/bin/podman") is False


def test_build_custom_mcp_run_argv():
    argv = build_custom_mcp_run_argv(
        runtime="docker",
        image="aion/sandbox:latest",
        slug="my_server",
        host_server_dir=Path("/host/mcp_servers/custom/my_server"),
        entrypoint="server.py",
        env={"CUSTOM_KEY": "val123"},
        memory="256m",
        cpus="0.5",
        pids="64",
    )
    assert argv[0] == "docker"
    assert "run" in argv
    assert "--rm" in argv
    assert "-i" in argv
    assert "--init" in argv
    assert "--cap-drop=ALL" in argv
    assert "--security-opt" in argv
    assert "no-new-privileges" in argv
    assert "--read-only" in argv
    assert "--tmpfs" in argv
    assert "/tmp:rw,noexec,nosuid,size=256m" in argv
    assert "--network=none" in argv
    assert "--memory" in argv
    assert "256m" in argv
    # Variables are forwarded by name only: values (credentials) must never appear
    # on the docker command line, which is visible in the host process list.
    assert argv[argv.index("CUSTOM_KEY") - 1] == "-e"
    assert not any("val123" in a for a in argv)
    # Unprivileged user under Docker (code mounted read-only, /tmp is a tmpfs).
    assert argv[argv.index("--user") + 1] == "65534:65534"
    assert "--entrypoint" in argv
    assert "python" in argv
    assert "aion/sandbox:latest" in argv
    assert argv[-2:] == ["-u", "server.py"]
    # Docker must not have Podman-specific flags
    assert "--userns=keep-id" not in argv


# ─────────────────────────────────────────────────────────────
# 5. Runtime & Spawn Guards
# ─────────────────────────────────────────────────────────────

def test_kill_switch_blocks_custom_mcp(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AION_CUSTOM_MCP_FORCE_DISABLE", "1")
    custom_cfg = {"aion_custom": {"name": "test", "version": "1.0.0"}}
    with pytest.raises(CustomMcpUnavailable) as exc:
        ensure_can_start("test_server", custom_cfg)
    assert "AION_CUSTOM_MCP_FORCE_DISABLE=1" in str(exc.value)


@pytest.mark.asyncio
async def test_prepare_custom_spawn_unsandboxed_dev(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Without a container engine, the dev flag lets the server run on the host."""
    monkeypatch.setenv("AION_CUSTOM_MCP_ALLOW_UNSANDBOXED", "1")
    monkeypatch.delenv("AION_CUSTOM_MCP_FORCE_DISABLE", raising=False)
    monkeypatch.setattr("src.mcp_custom.runtime.container_isolation_available", lambda: False)

    server_dir = tmp_path / "custom" / "demo_srv"
    server_dir.mkdir(parents=True)
    (server_dir / "server.py").write_text("print('ok')")

    monkeypatch.setattr("src.mcp_custom.paths.custom_root", lambda: tmp_path / "custom")
    monkeypatch.setattr("src.mcp_custom.runtime.server_dir", lambda slug: tmp_path / "custom" / slug)

    cfg = {
        "command": "python",
        "args": ["-u", "custom/demo_srv/server.py"],
        "env": {"FIXED_VAR": "hello"},
        "aion_custom": {
            "name": "Demo",
            "version": "1.0.0",
            "entrypoint": "server.py",
            "credential_mode": "none",
        },
    }

    cmd, args, env, cwd = await prepare_custom_spawn(
        "demo_srv",
        cfg,
        "python",
        ["-u", "server.py"],
        {},
        user_id="default",
        tenant_id="default",
    )
    assert cmd == sys.executable
    assert args == ["-u", str((server_dir / "server.py").resolve())]
    assert cwd == str(server_dir.resolve())
    assert env["FIXED_VAR"] == "hello"
    # Ensure backend secrets are not leaked
    assert "AION_CHAT_AUTH_SECRET" not in env
    assert "AION_DB_URL" not in env


# ─────────────────────────────────────────────────────────────
# 6. Real Container Jail Execution Test (Docker / Podman)
# ─────────────────────────────────────────────────────────────

def test_container_custom_mcp_jail_execution(tmp_path: Path):
    from src.security.container_runtime import get_container_runtime
    runtime = get_container_runtime()
    if not runtime.is_available():
        pytest.skip("Container runtime (Docker/Podman) not available")

    # Create dummy custom server
    srv_dir = tmp_path / "custom" / "hello_srv"
    srv_dir.mkdir(parents=True)
    server_py = srv_dir / "server.py"
    server_py.write_text("""
from fastmcp import FastMCP
mcp = FastMCP("test")
if __name__ == "__main__":
    print("READY")
""")

    import subprocess
    test_argv = [
        runtime.runtime,
        "run",
        "--rm",
        "--init",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",
        "-v",
        f"{srv_dir.resolve()}:/server:ro",
        "-w",
        "/server",
        "--network=none",
        "--entrypoint",
        "python",
        runtime.image,
        "-c",
        "from pathlib import Path; assert Path('/server/server.py').exists(); print('JAIL_ISOLATION_AND_MOUNT_OK')",
    ]
    proc = subprocess.run(test_argv, capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0
    assert "JAIL_ISOLATION_AND_MOUNT_OK" in proc.stdout


# ─────────────────────────────────────────────────────────────
# 7. FastMCP Stdio Roundtrip inside Container Jail
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_container_custom_mcp_fastmcp_stdio_roundtrip(tmp_path: Path):
    from src.security.container_runtime import get_container_runtime
    runtime = get_container_runtime()
    if not runtime.is_available():
        pytest.skip("Container runtime (Docker/Podman) not available")

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    srv_dir = tmp_path / "custom" / "calc_srv"
    srv_dir.mkdir(parents=True, exist_ok=True)
    server_py = srv_dir / "server.py"
    server_py.write_text("""from fastmcp import FastMCP

mcp = FastMCP("calc-server")

@mcp.tool()
def multiply(x: int, y: int) -> int:
    \"\"\"Multiplies two numbers.\"\"\"
    return x * y

if __name__ == "__main__":
    mcp.run()
""", encoding="utf-8")

    cmd, args, spawn_env = runtime.build_custom_mcp_spawn(
        "calc_server",
        server_path=srv_dir,
        entrypoint="server.py",
        env={"TEST_KEY": "val"},
    )
    server_params = StdioServerParameters(command=cmd, args=args, env=spawn_env)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            assert "multiply" in tool_names

            call_res = await session.call_tool("multiply", {"x": 6, "y": 7})
            assert call_res.content
            assert "42" in call_res.content[0].text


# ─────────────────────────────────────────────────────────────
# 8. Full Admin API Workflow Test (/admin/mcp-custom)
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_custom_mcp_api_workflow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from unittest.mock import AsyncMock, patch
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.admin_custom_mcp import router as custom_mcp_router
    from src.api.auth_login import ChatAuthIdentity, require_admin_role
    from src.mcp_custom.template import MANIFEST_TEMPLATE, SERVER_TEMPLATE

    monkeypatch.setenv("AION_CUSTOM_MCP_ENABLED", "1")

    app = FastAPI()
    app.include_router(custom_mcp_router, prefix="/admin")
    app.dependency_overrides[require_admin_role] = lambda: ChatAuthIdentity(
        authenticated=True,
        role="admin",
        user_row_id="admin_test",
        identifier="admin@test.local",
        via="token",
    )

    client = TestClient(app)

    # 1. Config
    res = client.get("/admin/mcp-custom/config")
    assert res.status_code == 200
    cfg = res.json()
    assert cfg["enabled"] is True
    assert "sandbox_available" in cfg

    # 2. Guide snippets: the manifest template shown/downloaded in admin-ui
    res_tmpl = client.get("/admin/mcp-custom/guide-template")
    assert res_tmpl.status_code == 200
    snippets = res_tmpl.json()
    assert snippets["aion_mcp_yaml"] == MANIFEST_TEMPLATE
    assert "mcp.run()" in snippets["server_py"]

    # The package a developer builds by following the guide: the two snippets
    # zipped in one folder (as "compress folder" does).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("example/server.py", SERVER_TEMPLATE)
        zf.writestr("example/aion-mcp.yaml", MANIFEST_TEMPLATE)
    guide_package = buf.getvalue()

    # 3. Upload starter template package
    def fake_verification(upload_id):
        """Stand-in for the jail verification (Docker is not needed by this test)."""
        from src.mcp_custom.verify import _update

        _update(upload_id, status="ok", tools=[{"name": "search_customer", "description": ""}])

    with (
        patch("src.mcp_integration_sync.sync_mcp_server_config_from_registry", AsyncMock()),
        patch("src.mcp_custom.install._audit", AsyncMock()),
        patch("src.mcp_custom.install.invalidate_runtime", AsyncMock()),
        patch("src.api.admin_custom_mcp.start_verification", fake_verification),
    ):
        files = {"file": ("example.zip", guide_package, "application/x-zip-compressed")}
        res_upload = client.post("/admin/mcp-custom/uploads", files=files)
        assert res_upload.status_code == 200, res_upload.text
        upload_id = res_upload.json()["upload_id"]
        # The upload response is taken before the verification finishes ("verifying");
        # once it has run, the review says "ready".
        review = client.get(f"/admin/mcp-custom/uploads/{upload_id}").json()
        assert review["status"] == "ready"
        slug = review["manifest"]["slug"]
        assert slug == "example_server"

        # 4. Activate
        res_act = client.post(
            f"/admin/mcp-custom/uploads/{upload_id}/activate",
            json={"replace_same_version": False},
        )
        assert res_act.status_code == 200, res_act.text
        act_data = res_act.json()
        assert act_data["server_slug"] == "example_server"
        assert act_data["version"] == "1.0.0"

        # Verify custom server installed
        from src.mcp_custom.paths import server_dir
        installed_dir = server_dir("example_server")
        assert installed_dir.is_dir()
        assert (installed_dir / "server.py").is_file()
        assert (installed_dir / "aion-mcp.yaml").is_file()

        # 5. List custom servers
        res_list = client.get("/admin/mcp-custom")
        assert res_list.status_code == 200
        servers = res_list.json()["servers"]
        assert any(s["server_slug"] == "example_server" for s in servers)

        # 6. Removal of custom artifacts
        from src.mcp_custom.install import remove_custom_artifacts
        remove_custom_artifacts("example_server")
        assert not installed_dir.exists()




# ───────────────────────── regression: custom entry overwritten by installs ─────────────────────────

_CUSTOM_ENTRY = {
    "command": "python",
    "args": ["-u", "custom/mcp_test_one/server.py"],
    "env": {},
    "aion_custom": {"name": "Test", "version": "1.0.0", "runtime": "python", "entrypoint": "server.py"},
}


@pytest.mark.parametrize("slug,expected", [("mcp_test_one", True), ("other_server", False)])
def test_install_endpoints_refuse_custom_slug(monkeypatch: pytest.MonkeyPatch, slug: str, expected: bool):
    """Zero-install/remote/script installs must not replace a custom server's registry entry.

    Regression: the Hub opened the zero-install wizard right after a custom upload and
    `install-zero` rewrote `mcp_test_1` as `npx -y mcp_test_1`, dropping `aion_custom`.
    """
    from fastapi import HTTPException

    from src.api import admin as admin_api

    monkeypatch.setattr(admin_api.mcp_manager, "load_registry", lambda *a, **k: None)
    monkeypatch.setattr(admin_api.mcp_manager, "_registry", {"mcp_test_one": _CUSTOM_ENTRY})
    if expected:
        with pytest.raises(HTTPException) as exc:
            admin_api._reject_custom_slug_overwrite(slug)
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "custom_mcp_slug"
    else:
        admin_api._reject_custom_slug_overwrite(slug)  # non-custom slugs are untouched


# ───────────────────────── isolation is preferred over the dev flag ─────────────────────────


@pytest.mark.asyncio
async def test_dev_flag_does_not_disable_working_jail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """With a container engine available, the server runs in the jail even when
    AION_CUSTOM_MCP_ALLOW_UNSANDBOXED=1 (the flag is only a fallback), and the
    credential value reaches the container through the private --env-file: neither
    the CLI argv nor the CLI's own environment."""
    monkeypatch.setenv("AION_CUSTOM_MCP_ALLOW_UNSANDBOXED", "1")
    monkeypatch.delenv("AION_CUSTOM_MCP_FORCE_DISABLE", raising=False)
    monkeypatch.setenv("AION_CONTAINER_RUNTIME", "docker")
    monkeypatch.setattr("src.mcp_custom.runtime.container_isolation_available", lambda: True)
    server = tmp_path / "custom" / "jail_srv"
    server.mkdir(parents=True)
    (server / "server.py").write_text("print('ok')")
    monkeypatch.setattr("src.mcp_custom.runtime.server_dir", lambda slug: tmp_path / "custom" / slug)

    async def fake_credentials(*_a, **_k):
        return {"SECRET_TOKEN": "s3cr3t"}

    monkeypatch.setattr("src.mcp_custom.runtime._credential_env", fake_credentials)
    import src.security.container_runtime as cr

    monkeypatch.setattr(cr, "_RUNTIME", None)
    cfg = {"aion_custom": {"name": "J", "version": "1.0.0", "entrypoint": "server.py", "credential_mode": "org_shared"}}
    cmd, args, env, cwd = await prepare_custom_spawn("jail_srv", cfg, "python", [], {}, user_id="u1", tenant_id="default")
    assert cmd == "docker" and "run" in args and cwd is None
    assert not any("s3cr3t" in a for a in args)
    assert "SECRET_TOKEN" not in env
    env_file = Path(args[args.index("--env-file") + 1])
    assert "SECRET_TOKEN=s3cr3t" in env_file.read_text(encoding="utf-8").splitlines()


# ───────────────────────── deletion removes every file of the server ─────────────────────────


def _make_custom_layout(root: Path, slug: str, *, marker: bool) -> None:
    import json as _json

    from src.mcp_custom.install import INSTALL_MARKER

    code = root / slug
    code.mkdir(parents=True)
    (code / "server.py").write_text("print('x')")
    if marker:
        (code / INSTALL_MARKER).write_text("{}")
    (root / ".versions" / slug / "1.0.0__x").mkdir(parents=True)
    staged = root / ".staging" / ("a" * 32)
    staged.mkdir(parents=True)
    (staged / "upload.json").write_text(_json.dumps({"manifest": {"slug": slug}, "suggested_slug": slug}))


def test_remove_custom_artifacts_removes_code_versions_and_uploads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Deleting a custom server removes its code, archived versions and pending uploads."""
    from src.mcp_custom import install

    root = tmp_path / "custom"
    monkeypatch.setattr(install, "custom_root", lambda: root)
    monkeypatch.setattr(install, "server_dir", lambda s: root / s)
    monkeypatch.setattr(install, "versions_root", lambda: root / ".versions")
    monkeypatch.setattr("src.mcp_custom.runtime.container_isolation_available", lambda: False)
    _make_custom_layout(root, "gone_srv", marker=True)

    result = install.remove_custom_artifacts("gone_srv")

    assert not (root / "gone_srv").exists()
    assert not (root / ".versions" / "gone_srv").exists()
    assert not (root / ".staging" / ("a" * 32)).exists()
    assert result["failed"] == []
    assert install.has_custom_artifacts("gone_srv") is False


def test_cleanup_orphans_only_removes_aion_installed_folders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """At startup, folders AION installed (marker) without a registry entry are removed;
    folders copied by hand (no marker) are kept for a later activation."""
    from src.mcp_custom import install

    root = tmp_path / "custom"
    monkeypatch.setattr(install, "custom_root", lambda: root)
    monkeypatch.setattr(install, "server_dir", lambda s: root / s)
    monkeypatch.setattr(install, "versions_root", lambda: root / ".versions")
    monkeypatch.setattr("src.mcp_custom.runtime.container_isolation_available", lambda: False)
    monkeypatch.setattr("src.mcp_custom.package.cleanup_expired", lambda: 0)
    from src.mcp_manager import mcp_manager

    monkeypatch.setattr(mcp_manager, "load_registry", lambda *a, **k: None)
    monkeypatch.setattr(mcp_manager, "_registry", {"kept_srv": {"aion_custom": {"version": "1.0.0"}}})
    _make_custom_layout(root, "orphan_srv", marker=True)
    (root / "manual_srv").mkdir()
    (root / "manual_srv" / "server.py").write_text("print('x')")
    (root / "kept_srv").mkdir()
    (root / "kept_srv" / install.INSTALL_MARKER).write_text("{}")

    summary = install.cleanup_orphans()

    assert "orphan_srv" in summary["servers"]
    assert not (root / "orphan_srv").exists()
    assert (root / "manual_srv").is_dir()
    assert (root / "kept_srv").is_dir()


# ───────────────────────── clearing a shared credential ─────────────────────────


def test_clearing_custom_org_credential_deletes_stored_value(monkeypatch: pytest.MonkeyPatch):
    """Emptying a shared credential in Configure deletes the encrypted copy (the custom
    spawn reads only the store) and puts the ${KEY} placeholder back."""
    import asyncio

    from src.api import admin as admin_api

    deleted = []

    async def fake_delete(owner, slug, key, *, tenant_id="default"):
        deleted.append((owner, slug, key))
        return True

    monkeypatch.setattr("src.runtime.credential_store.delete_credential", fake_delete)
    env = {"CATALOG_SECRET_KEY": "", "OTHER_SECRET": "${OTHER_SECRET}", "CATALOG_CURRENCY": "EUR"}
    out = asyncio.run(
        admin_api._clear_custom_org_credentials("cat", env, ["CATALOG_SECRET_KEY", "OTHER_SECRET"])
    )
    assert out["CATALOG_SECRET_KEY"] == "${CATALOG_SECRET_KEY}"
    assert out["CATALOG_CURRENCY"] == "EUR"
    assert sorted(deleted) == [("default", "cat", "CATALOG_SECRET_KEY"), ("org_shared", "cat", "CATALOG_SECRET_KEY")]


def test_guide_manifest_template_is_valid_and_matches_server():
    """The aion-mcp.yaml template shown in the admin-ui guide parses with the real
    parser and declares exactly the variables the server snippet reads."""
    from src.mcp_custom.template import MANIFEST_TEMPLATE, SERVER_TEMPLATE

    manifest = parse_manifest_text(MANIFEST_TEMPLATE)
    assert manifest.entrypoint == "server.py"
    declared = set(manifest.env) | {f.key for f in manifest.credentials.fields}
    assert declared == {"CRM_API_KEY", "CRM_BASE_URL"}
    for key in declared:
        assert key in SERVER_TEMPLATE



# ───────────────────────── phase A: free dependencies, verified in the jail ─────────────────────────


def _zip(files: Dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


_MANIFEST_DEPS = "aion_mcp: 1\nslug: deps_srv\nname: Deps\ndescription: d\nversion: 1.0.0\n"
_SERVER_OK = "from fastmcp import FastMCP\nmcp = FastMCP('x')\n@mcp.tool()\ndef t() -> str:\n    'x'\n    return 'x'\nmcp.run()\n"


def test_requirements_are_accepted_and_normalised(monkeypatch: pytest.MonkeyPatch):
    """Any package is accepted: requirements are listed for the build, not checked against a whitelist."""
    from src.mcp_custom.package import NORMALIZED_REQUIREMENTS, upload_src_dir

    staged = stage_upload(
        "deps.zip",
        _zip({"server.py": _SERVER_OK, "aion-mcp.yaml": _MANIFEST_DEPS, "requirements.txt": "# libs\nrequests==2.32.3\nhumanize\n"}),
        actor="t",
    )
    assert staged.errors == []
    assert staged.requirements == ["requests==2.32.3", "humanize"]
    assert staged.status == "verifying"
    normalized = upload_src_dir(staged.upload_id) / NORMALIZED_REQUIREMENTS
    assert normalized.read_text(encoding="utf-8").split() == ["requests==2.32.3", "humanize"]


def test_pyproject_dependencies_are_used_without_building_the_project():
    """pyproject.toml: only [project].dependencies are installed (the project is never built)."""
    pyproject = '[project]\nname = "x"\nversion = "1"\ndependencies = ["httpx>=0.27", "humanize"]\n'
    staged = stage_upload(
        "deps.zip",
        _zip({"server.py": _SERVER_OK, "aion-mcp.yaml": _MANIFEST_DEPS, "pyproject.toml": pyproject}),
        actor="t",
    )
    assert staged.requirements == ["httpx>=0.27", "humanize"]


def test_deps_build_argv_is_jailed_and_wheels_only():
    """The dependency build runs in the same jail: read-only code, only /deps writable, wheels only."""
    from src.security.container_policy import build_custom_mcp_deps_argv

    argv = build_custom_mcp_deps_argv(
        runtime="docker",
        image="aion/sandbox:latest",
        slug="deps_srv",
        host_src_dir=Path("/host/custom/.staging/x/src"),
        host_deps_dir=Path("/host/custom/.deps/k.building-x"),
        requirements_rel=".aion-requirements.txt",
    )
    joined = " ".join(argv)
    assert "--cap-drop=ALL" in argv and "--read-only" in argv and "no-new-privileges" in argv
    assert ":/server:ro" in joined and ":/deps:rw" in joined
    assert "--only-binary=:all:" in argv
    assert argv[argv.index("--user") + 1] == "65534:65534"
    assert "/app/data" not in joined and ".env" not in joined


def test_run_argv_mounts_deps_read_only():
    """At run time the dependencies are mounted read-only."""
    argv = build_custom_mcp_run_argv(
        runtime="docker",
        image="aion/sandbox:latest",
        slug="deps_srv",
        host_server_dir=Path("/host/custom/deps_srv"),
        host_deps_dir=Path("/host/custom/.deps/abc"),
    )
    assert any(a.endswith(":/deps:ro") for a in argv)


def test_jail_env_uses_tmp_home_and_deps_path():
    """In the jail HOME/caches are in /tmp (read-only root) and /deps is on PYTHONPATH."""
    from src.mcp_custom.runtime import finalize_process_env

    env = finalize_process_env({"HOME": "/app/data/users/u/mcp_home", "XDG_CONFIG_HOME": "/app/x"}, in_container=True, deps_dir=Path("/whatever"))
    assert env["HOME"] == "/tmp" and env["PYTHONPATH"] == "/deps"
    assert "XDG_CONFIG_HOME" not in env


def test_activation_requires_successful_verification(monkeypatch: pytest.MonkeyPatch):
    """An upload still verifying, or that failed the verification, cannot go live."""
    import asyncio

    from src.mcp_custom.install import ActivationError, activate
    from src.mcp_custom.verify import _update

    staged = stage_upload("ok.zip", _zip({"server.py": _SERVER_OK, "aion-mcp.yaml": _MANIFEST_DEPS}), actor="t")
    with pytest.raises(ActivationError) as exc:
        asyncio.run(activate(staged.upload_id, actor="t"))
    assert exc.value.code == "verification_pending"
    _update(staged.upload_id, status="failed", error="ModuleNotFoundError: No module named 'x'")
    with pytest.raises(ActivationError) as exc:
        asyncio.run(activate(staged.upload_id, actor="t"))
    assert exc.value.code == "verification_failed"


def test_gc_deps_keeps_only_referenced_sets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Dependency folders nobody references are deleted; in-use and fresh builds stay."""
    from src.mcp_custom import verify

    root = tmp_path / "deps"
    for name in ("used", "unused", "abc.building-x"):
        (root / name).mkdir(parents=True)
    monkeypatch.setattr(verify, "deps_root", lambda: root)
    monkeypatch.setattr(verify, "referenced_deps_keys", lambda: {"used"})

    removed = verify.gc_deps()

    assert removed == ["unused"]
    assert (root / "used").is_dir() and (root / "abc.building-x").is_dir()


# ───────────────────────── Podman (production engine) ─────────────────────────


def test_podman_custom_mounts_use_shared_selinux_label(monkeypatch: pytest.MonkeyPatch):
    """Server and dependency folders are mounted by several containers: shared label ,z (not ,Z)."""
    monkeypatch.setenv("AION_SANDBOX_CONTAINER_SELINUX", "1")
    argv = build_custom_mcp_run_argv(
        runtime="podman",
        image="aion/sandbox:latest",
        slug="srv",
        host_server_dir=Path("/srv/aion/mcp_servers/custom/srv"),
        host_deps_dir=Path("/srv/aion/mcp_servers/custom/.deps/k"),
    )
    mounts = [a for a in argv if ":/server:" in a or ":/deps:" in a]
    assert len(mounts) == 2 and all(m.endswith(",z") for m in mounts)


def test_podman_build_uses_engine_default_network(monkeypatch: pytest.MonkeyPatch):
    """Podman: no forced network for the build (pasta/slirp4netns chosen by the engine)."""
    from src.security.container_policy import build_custom_mcp_deps_argv

    argv = build_custom_mcp_deps_argv(
        runtime="podman",
        image="aion/sandbox:latest",
        slug="srv",
        host_src_dir=Path("/srv/aion/mcp_servers/custom/.staging/x/src"),
        host_deps_dir=Path("/srv/aion/mcp_servers/custom/.deps/k.building-x"),
        requirements_rel=".aion-requirements.txt",
    )
    assert not any(a.startswith("--network") for a in argv)
    assert "--only-binary=:all:" in argv


def test_host_path_derived_from_sandbox_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Without AION_CUSTOM_MCP_HOST_DIR the host path comes from AION_SANDBOX_HOST_DATA_DIR."""
    from src.security import container_runtime

    monkeypatch.delenv("AION_CUSTOM_MCP_HOST_DIR", raising=False)
    monkeypatch.delenv("AION_SANDBOX_HOST_REPO", raising=False)
    monkeypatch.setenv("AION_SANDBOX_HOST_DATA_DIR", "/srv/aion/data")
    path = container_runtime.resolve_custom_mcp_host_path(Path("/app/mcp_servers/custom/.deps/abc"))
    assert path.as_posix().endswith("/srv/aion/mcp_servers/custom/.deps/abc")
