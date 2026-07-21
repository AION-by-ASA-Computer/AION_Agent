"""Unit tests for container sandbox policy and runtime helpers."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src.security.container_paths import (
    SANDBOX_FS_POLICY_CONTAINER_PATH,
    resolve_fs_policy_host_mount,
    resolve_host_repo_path,
)
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

    def test_run_argv_mounts_fs_policy_when_configured(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "aion"
            data = repo / "data"
            config = repo / "config"
            config.mkdir(parents=True)
            (config / "fs_policy.yaml").write_text(
                "exec:\n  enabled: true\n", encoding="utf-8"
            )
            session_host = data / "sessions" / "sess-1234"
            session_host.mkdir(parents=True)
            with patch.dict(
                os.environ,
                {
                    "AION_FS_POLICY_PATH": "config/fs_policy.yaml",
                    "AION_DATA_DIR": str(data),
                    "AION_SANDBOX_HOST_DATA_DIR": str(data),
                },
                clear=False,
            ):
                argv = build_container_run_argv(
                    runtime="podman",
                    image="aion/sandbox:latest",
                    session_id="sess-1234",
                    session_host_path=session_host,
                )
            joined = " ".join(argv)
            policy_host = (config / "fs_policy.yaml").resolve()
            self.assertIn(
                f"{policy_host}:{SANDBOX_FS_POLICY_CONTAINER_PATH}:ro",
                joined,
            )
            self.assertIn(
                f"AION_FS_POLICY_PATH={SANDBOX_FS_POLICY_CONTAINER_PATH}",
                joined,
            )

    def test_run_argv_mounts_host_src_when_host_data_dir_set(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "aion"
            data = repo / "data"
            src = repo / "src"
            src.mkdir(parents=True)
            (repo / "requirements-sandbox-skills.txt").write_text(
                "defusedxml\n", encoding="utf-8"
            )
            session_host = data / "sessions" / "sess-1234"
            session_host.mkdir(parents=True)
            with patch.dict(
                os.environ,
                {"AION_SANDBOX_HOST_DATA_DIR": str(data)},
                clear=False,
            ):
                argv = build_container_run_argv(
                    runtime="podman",
                    image="aion/sandbox:latest",
                    session_id="sess-1234",
                    session_host_path=session_host,
                )
            joined = " ".join(argv)
            self.assertIn(f"{src.resolve()}:/app/src:ro", joined)
            self.assertIn(
                f"{(repo / 'requirements-sandbox-skills.txt').resolve()}"
                ":/app/requirements-sandbox-skills.txt:ro",
                joined,
            )


class TestContainerPaths(unittest.TestCase):
    def test_resolve_host_repo_path(self):
        with patch.dict(
            os.environ,
            {
                "AION_DATA_DIR": "/app/data",
                "AION_SANDBOX_HOST_DATA_DIR": "/host/aion/data",
            },
            clear=False,
        ):
            mapped = resolve_host_repo_path(Path("/app/config/fs_policy.yaml"))
        self.assertEqual(mapped, Path("/host/aion/config/fs_policy.yaml").resolve())

    def test_resolve_fs_policy_host_mount(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "aion"
            data = repo / "data"
            config = repo / "config"
            config.mkdir(parents=True)
            policy = config / "fs_policy.yaml"
            policy.write_text("exec:\n  enabled: true\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "AION_FS_POLICY_PATH": "config/fs_policy.yaml",
                    "AION_DATA_DIR": str(data),
                    "AION_SANDBOX_HOST_DATA_DIR": str(data),
                },
                clear=False,
            ):
                host = resolve_fs_policy_host_mount()
            self.assertEqual(host, policy.resolve())

    def test_resolve_fs_policy_host_mount_when_host_path_invisible_in_backend(self):
        """Podman host path may not exist inside the backend Docker filesystem."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "aion"
            data = repo / "data"
            config = repo / "config"
            config.mkdir(parents=True)
            policy = config / "fs_policy.yaml"
            policy.write_text("exec:\n  enabled: true\n", encoding="utf-8")
            invisible_host = Path("/host/aion/config/fs_policy.yaml")
            with patch.dict(
                os.environ,
                {
                    "AION_FS_POLICY_PATH": "config/fs_policy.yaml",
                    "AION_DATA_DIR": str(data),
                    "AION_SANDBOX_HOST_DATA_DIR": str(data),
                },
                clear=False,
            ):
                original_is_file = Path.is_file

                def _is_file(self):
                    if self == invisible_host:
                        return False
                    return original_is_file(self)

                with patch.object(Path, "is_file", _is_file):
                    with patch(
                        "src.security.container_paths.resolve_host_repo_path",
                        return_value=invisible_host,
                    ):
                        host = resolve_fs_policy_host_mount()
            self.assertEqual(host, invisible_host)


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
