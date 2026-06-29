"""Tests for flat /session mount layout inside sandbox containers."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.session_workspace import session_root


class TestSessionWorkspaceFlat(unittest.TestCase):
    def test_flat_mount_returns_data_root(self):
        with patch.dict(
            os.environ,
            {"AION_DATA_DIR": "/session", "AION_SANDBOX_FLAT_SESSION_ROOT": "1"},
            clear=False,
        ):
            root = session_root("abcd-1234-test")
        self.assertEqual(str(root), "/session")

    def test_host_layout_uses_sessions_subdir(self):
        with patch.dict(os.environ, {"AION_DATA_DIR": "data"}, clear=False):
            root = session_root("abcd-1234-test")
        self.assertTrue(str(root).endswith("data/sessions/abcd-1234-test"))


if __name__ == "__main__":
    unittest.main()
