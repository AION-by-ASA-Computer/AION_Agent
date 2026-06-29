"""Tests for unified session subprocess runner."""
from __future__ import annotations

import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from src.security.session_runner import (
    SandboxBackendUnavailable,
    run_session_subprocess,
)


class TestSessionRunner(unittest.TestCase):
    def test_subprocess_backend_runs_plain(self):
        with patch.dict(os.environ, {"AION_SANDBOX_BACKEND": "subprocess"}, clear=False):
            with patch("src.security.session_runner.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
                run_session_subprocess(
                    "sess-1234",
                    ["echo", "hi"],
                    cwd="/tmp",
                    env={"PATH": "/usr/bin"},
                    timeout=5.0,
                )
                mock_run.assert_called_once()
                self.assertEqual(mock_run.call_args.kwargs["env"], {"PATH": "/usr/bin"})

    def test_deprecated_openshell_backend_maps_to_subprocess(self):
        with patch.dict(os.environ, {"AION_SANDBOX_BACKEND": "openshell"}, clear=False):
            with patch("src.security.session_runner.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
                run_session_subprocess(
                    "sess-1234",
                    ["pip", "install", "requests"],
                    cwd="/tmp",
                    env={},
                )
                mock_run.assert_called_once()

    def test_container_unavailable_fail_closed(self):
        with patch.dict(
            os.environ,
            {
                "AION_SANDBOX_BACKEND": "container",
                "AION_SANDBOX_FAIL_CLOSED": "1",
            },
            clear=False,
        ):
            with patch(
                "src.security.session_runner._container_runtime_available",
                return_value=False,
            ):
                with patch("src.security.session_runner.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock()
                    with self.assertRaises(SandboxBackendUnavailable):
                        run_session_subprocess(
                            "sess-1234",
                            ["python", "-V"],
                            cwd="/tmp",
                            env={},
                        )


if __name__ == "__main__":
    unittest.main()
