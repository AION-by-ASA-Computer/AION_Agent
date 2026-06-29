"""Unit tests for container sandbox policy and runtime helpers."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src.security.container_policy import (
    build_container_run_argv,
    container_name_for_session,
)
from src.security.container_runtime import (
    ContainerRuntime,
    prepare_session_host_mount,
    resolve_session_host_mount_path,
    sandbox_container_mode_enabled,
)


class TestContainerPolicy(unittest.TestCase):
    def test_run_argv_hardening_flags(self):
        with patch.dict(
            os.environ,
            {
                "AION_SANDBOX_ALLOW_PACKAGE_INSTALL": "0",
                "AION_SANDBOX_ALLOW_NPM_INSTALL": "0",
            },
            clear=False,
        ):
            argv = build_container_run_argv(
                runtime="podman",
                image="aion/sandbox:latest",
                session_id="abcd-1234-test",
                session_host_path=Path("/data/sessions/abcd-1234-test"),
            )
        joined = " ".join(argv)
        self.assertIn("--cap-drop=ALL", joined)
        self.assertIn("--read-only", joined)
        self.assertIn("--network=none", joined)
        self.assertIn("/data/sessions/abcd-1234-test:/session:rw", joined)
        self.assertIn("AION_DATA_DIR=/session", joined)
        self.assertTrue(argv[-1].endswith("aion/sandbox:latest"))

    def test_container_name_is_stable(self):
        a = container_name_for_session("session-abc")
        b = container_name_for_session("session-abc")
        c = container_name_for_session("session-xyz")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith("aion-sandbox-"))

    def test_network_when_package_install_allowed(self):
        with patch.dict(
            os.environ,
            {"AION_SANDBOX_ALLOW_PACKAGE_INSTALL": "1"},
            clear=False,
        ):
            argv = build_container_run_argv(
                runtime="podman",
                image="aion/sandbox:latest",
                session_id="sess-1234",
                session_host_path=Path("/tmp/sess"),
            )
        self.assertTrue(
            any("network=" in arg and "none" not in arg for arg in argv)
            or any(
                arg.startswith("--network=") and arg != "--network=none" for arg in argv
            )
        )

    def test_run_user_when_host_data_dir_set(self):
        with patch.dict(
            os.environ,
            {
                "AION_SANDBOX_HOST_DATA_DIR": "/host/data",
                "AION_SANDBOX_HOST_UID": "1000",
                "AION_SANDBOX_HOST_GID": "1000",
            },
            clear=False,
        ):
            argv = build_container_run_argv(
                runtime="podman",
                image="aion/sandbox:latest",
                session_id="sess-1234",
                session_host_path=Path("/host/data/sessions/sess-1234"),
            )
        self.assertIn("--user", argv)
        self.assertIn("--userns=keep-id", argv)
        self.assertIn("1000:1000", argv)


class TestContainerRuntime(unittest.TestCase):
    def test_sandbox_container_mode_env_gate(self):
        with patch.dict(
            os.environ,
            {
                "AION_SANDBOX_BACKEND": "container",
                "AION_SANDBOX_MCP_JAIL": "1",
            },
            clear=False,
        ):
            self.assertTrue(sandbox_container_mode_enabled())
        with patch.dict(
            os.environ,
            {"AION_SANDBOX_BACKEND": "subprocess", "AION_SANDBOX_MCP_JAIL": "1"},
            clear=False,
        ):
            self.assertFalse(sandbox_container_mode_enabled())

    def test_build_stdio_spawn_returns_podman(self):
        rt = ContainerRuntime()
        with patch.object(rt, "image", "aion/sandbox:test"):
            cmd, args, env = rt.build_stdio_spawn(
                "test-sess-1234",
                profile_slug="aion_std",
                user_id="user1",
                tenant_id="default",
            )
        self.assertEqual(cmd, rt.runtime)
        self.assertIn("run", args)
        self.assertIn("AION_CURRENT_PROFILE_SLUG=aion_std", " ".join(args))

    def test_resolve_session_host_mount_path(self):
        with patch.dict(
            os.environ,
            {
                "AION_DATA_DIR": "/app/data",
                "AION_SANDBOX_HOST_DATA_DIR": "/host/aion/data",
            },
            clear=False,
        ):
            mapped = resolve_session_host_mount_path(
                Path("/app/data/sessions/chat-1234")
            )
        self.assertEqual(mapped, Path("/host/aion/data/sessions/chat-1234").resolve())

    def test_prepare_session_host_mount_chowns(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "sess-1234"
            workspace = session / "workspace"
            venv_py = session / ".venv" / "bin" / "python3.13"
            workspace.mkdir(parents=True)
            venv_py.parent.mkdir(parents=True)
            venv_py.symlink_to("/usr/local/bin/python3.13")
            with patch.dict(
                os.environ,
                {
                    "AION_SANDBOX_HOST_DATA_DIR": tmp,
                    "AION_SANDBOX_HOST_UID": str(os.getuid()),
                    "AION_SANDBOX_HOST_GID": str(os.getgid()),
                },
                clear=False,
            ):
                prepare_session_host_mount(session)
            st = workspace.stat()
            self.assertEqual(st.st_uid, os.getuid())
            self.assertEqual(st.st_gid, os.getgid())
            if venv_py.exists():
                self.assertTrue(venv_py.is_symlink())


if __name__ == "__main__":
    unittest.main()
