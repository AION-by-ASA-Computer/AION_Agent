"""Escape-policy tests: container argv must not expose host secrets paths."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.security.container_policy import build_container_run_argv


class TestSessionSandboxEscapePolicy(unittest.TestCase):
    def test_no_host_repo_or_env_mounts(self):
        argv = build_container_run_argv(
            runtime="podman",
            image="aion/sandbox:latest",
            session_id="escape-test-1234",
            session_host_path=Path("/app/data/sessions/escape-test-1234"),
        )
        mount_args = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
        for mount in mount_args:
            self.assertNotIn("/app/.env", mount)
            self.assertNotIn("aion.db", mount)
            self.assertTrue(
                mount.startswith("/app/data/sessions/escape-test-1234:/session")
            )

    def test_read_only_rootfs_and_no_new_privileges(self):
        argv = build_container_run_argv(
            runtime="podman",
            image="aion/sandbox:latest",
            session_id="x",
            session_host_path=Path("/tmp/x"),
        )
        self.assertIn("--read-only", argv)
        self.assertIn("no-new-privileges", argv)


if __name__ == "__main__":
    unittest.main()
