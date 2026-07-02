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
        expected_prefix = (
            f"{Path('/app/data/sessions/escape-test-1234').resolve()}:/session"
        )
        for mount in mount_args:
            self.assertNotIn("/app/.env", mount)
            self.assertNotIn("aion.db", mount)

        session_mounts = [m for m in mount_args if ":/session" in m]
        self.assertEqual(len(session_mounts), 1)
        self.assertTrue(session_mounts[0].startswith(expected_prefix))

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
