"""Tests for session sandbox environment scrubbing."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src.security.session_env import build_session_env


class TestSessionEnv(unittest.TestCase):
    def test_strips_secret_aion_vars(self):
        with patch.dict(
            os.environ,
            {
                "AION_API_URL": "http://secret:8000/v1",
                "AION_DB_URL": "sqlite:///secret.db",
                "AION_CHAT_AUTH_SECRET": "super-secret",
                "PATH": "/usr/bin",
                "LANG": "C.UTF-8",
            },
            clear=False,
        ):
            env = build_session_env(
                "test-sess-1234",
                session_root=Path("/tmp/sessions/test-sess-1234"),
            )
        self.assertNotIn("AION_API_URL", env)
        self.assertNotIn("AION_DB_URL", env)
        self.assertNotIn("AION_CHAT_AUTH_SECRET", env)
        self.assertEqual(env["HOME"], str(Path("/tmp/sessions/test-sess-1234").resolve()))
        self.assertEqual(env["AION_CHAT_SESSION_ID"], "test-sess-1234")
        self.assertEqual(
            env["AION_DATA_DIR"],
            str(Path("/tmp/sessions/test-sess-1234").resolve()),
        )

    def test_scrub_secrets_from_env(self):
        from src.security.session_env import scrub_secrets_from_env

        env = {
            "PATH": "/usr/bin",
            "MYSQL_PASSWORD": "secret",
            "AION_API_URL": "http://x",
            "AION_CHAT_SESSION_ID": "abc",
        }
        scrub_secrets_from_env(env)
        self.assertNotIn("MYSQL_PASSWORD", env)
        self.assertNotIn("AION_API_URL", env)
        self.assertIn("AION_CHAT_SESSION_ID", env)

    def test_allowlist_includes_path(self):
        with patch.dict(os.environ, {"PATH": "/custom/bin:/usr/bin"}, clear=False):
            env = build_session_env(
                "abcd-1234",
                session_root=Path("/data/sessions/abcd-1234"),
            )
        self.assertIn("/custom/bin", env["PATH"])

    def test_venv_dir_sets_virtual_env(self):
        vdir = Path("/data/sessions/x/.venv")
        env = build_session_env(
            "abcd-1234",
            session_root=Path("/data/sessions/x"),
            venv_dir=vdir,
        )
        self.assertEqual(env["VIRTUAL_ENV"], str(vdir.resolve()))


if __name__ == "__main__":
    unittest.main()
