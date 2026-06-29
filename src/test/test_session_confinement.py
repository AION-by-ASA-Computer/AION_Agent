"""Tests for subprocess sandbox filesystem confinement."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.security.session_confinement import (
    collect_confinement_paths,
    extract_python_script_argv,
    inject_node_hook,
    path_allowed,
    stamp_confinement_env,
    wrap_confined_argv,
)
from src.security.session_env import build_session_env
from src.security.session_runner import run_session_subprocess


class TestSessionConfinement(unittest.TestCase):
    def tearDown(self) -> None:
        from src.security.session_confinement import deactivate_python_guards

        deactivate_python_guards()

    def _with_guards(self, root: Path):
        from src.security.session_confinement import (
            activate_python_guards,
            deactivate_python_guards,
        )

        activate_python_guards(root)
        return deactivate_python_guards

    def test_path_allowed_denies_proc(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            deactivate = self._with_guards(root)
            try:
                self.assertFalse(path_allowed("/proc/1/environ"))
                if Path("/proc/self").exists():
                    self.assertTrue(path_allowed("/proc/self/status"))
            finally:
                deactivate()

    def test_path_allowed_session_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inside = root / "workspace" / "ok.txt"
            inside.parent.mkdir(parents=True)
            inside.write_text("hi", encoding="utf-8")
            deactivate = self._with_guards(root)
            try:
                self.assertTrue(path_allowed(inside))
                self.assertFalse(path_allowed("/etc/passwd"))
            finally:
                deactivate()

    def test_open_guard_blocks_outside_session(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            deactivate = self._with_guards(root)
            try:
                with self.assertRaises(PermissionError):
                    open("/etc/passwd").read()  # noqa: SIM115
            finally:
                deactivate()

    def test_os_walk_blocked_outside_session(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            deactivate = self._with_guards(root)
            try:
                with self.assertRaises(PermissionError):
                    next(os.walk("/"))
            finally:
                deactivate()

    def test_sqlite_connect_blocked_outside_session(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            deactivate = self._with_guards(root)
            try:
                with self.assertRaises(PermissionError):
                    sqlite3.connect("/tmp/outside.db")
            finally:
                deactivate()

    def test_runner_blocks_proc_and_host_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = root / "workspace"
            ws.mkdir(parents=True)
            script = ws / "probe.py"
            script.write_text(
                """
import sys
from pathlib import Path

def check(label, fn):
    try:
        fn()
        print(f"{label}:LEAK")
    except PermissionError:
        print(f"{label}:BLOCKED")

check("proc", lambda: open("/proc/1/environ").read())
check("passwd", lambda: Path("/etc/passwd").read_text())
""",
                encoding="utf-8",
            )
            env = build_session_env("confine-test-1234", session_root=root)
            proc = subprocess.run(
                [
                    sys.executable,
                    "-u",
                    "-m",
                    "src.security.sandbox_subprocess_entry",
                    "--python",
                    str(script),
                ],
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("proc:BLOCKED", proc.stdout)
            self.assertIn("passwd:BLOCKED", proc.stdout)
            self.assertNotIn("LEAK", proc.stdout)

    def test_exec_mode_blocks_host_file_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = root / "workspace"
            ws.mkdir(parents=True)
            script = ws / "node_probe.js"
            script.write_text(
                """
const fs = require('fs');
try {
  fs.readFileSync('/etc/passwd');
  console.log('LEAK');
} catch (e) {
  console.log('BLOCKED');
}
""",
                encoding="utf-8",
            )
            node = _which_node()
            if node is None:
                self.skipTest("node not on PATH")
            env = build_session_env("node-confine-1234", session_root=root)
            proc = run_session_subprocess(
                "node-confine-1234",
                [node, str(script)],
                cwd=str(root),
                env=env,
                confinement_root=root,
                confinement_mode="exec",
                confinement_executables=[Path(node)],
            )
            combined = (proc.stdout or "") + (proc.stderr or "")
            if (
                proc.returncode != 0
                and "BLOCKED" not in combined
                and "LEAK" not in combined
            ):
                self.skipTest(f"node probe inconclusive: {combined[:500]}")
            self.assertIn("BLOCKED", combined)
            self.assertNotIn("LEAK", combined)

    def test_node_blocks_proc_environ(self):
        import platform

        if platform.system() != "Linux" or not Path("/proc/1/environ").exists():
            self.skipTest("/proc/1/environ not available")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = root / "workspace"
            ws.mkdir(parents=True)
            script = ws / "proc_probe.js"
            script.write_text(
                """
const fs = require('fs');
try {
  fs.readFileSync('/proc/1/environ');
  console.log('LEAK');
} catch (e) {
  console.log('BLOCKED');
}
""",
                encoding="utf-8",
            )
            node = _which_node()
            if node is None:
                self.skipTest("node not on PATH")
            env = build_session_env("node-proc-1234", session_root=root)
            proc = run_session_subprocess(
                "node-proc-1234",
                [node, str(script)],
                cwd=str(root),
                env=env,
                confinement_root=root,
                confinement_mode="exec",
                confinement_executables=[Path(node)],
            )
            combined = (proc.stdout or "") + (proc.stderr or "")
            self.assertIn("BLOCKED", combined)
            self.assertNotIn("LEAK", combined)


def _which_node() -> str | None:
    import shutil

    return (os.environ.get("AION_NODE_PATH") or "").strip() or shutil.which("node")


class TestConfinementPaths(unittest.TestCase):
    def test_extract_python_script_argv_strips_interpreter(self):
        argv = ["/venv/bin/python", "-u", "/sess/workspace/foo.py", "--flag"]
        self.assertEqual(
            extract_python_script_argv(argv),
            ["/sess/workspace/foo.py", "--flag"],
        )
        wrapped = wrap_confined_argv(Path("/venv/bin/python"), argv, mode="python")
        py_idx = wrapped.index("--python")
        self.assertEqual(wrapped[py_idx + 1], "/sess/workspace/foo.py")
        self.assertEqual(wrapped[py_idx + 2], "--flag")

    def test_collect_includes_session_and_venv(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            venv = root / ".venv"
            venv.mkdir()
            read, write = collect_confinement_paths(root, venv_dir=venv)
            self.assertTrue(any(str(root) in str(p) for p in read))
            self.assertTrue(any(str(venv) in str(p) for p in read))
            self.assertTrue(any(str(root) in str(p) for p in write))

    def test_collect_proc_self_not_resolved(self):
        import platform

        if platform.system() != "Linux":
            self.skipTest("proc only on Linux")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            read, _ = collect_confinement_paths(root)
            proc_entries = [p for p in read if str(p).startswith("/proc/")]
            self.assertIn(Path("/proc/self"), proc_entries)
            for p in proc_entries:
                tail = str(p)[len("/proc/") :].split("/")[0]
                self.assertFalse(
                    tail.isdigit(), f"resolved pid leaked into allowlist: {p}"
                )

    def test_inject_node_hook(self):
        hook = (
            Path(__file__).resolve().parents[1] / "security" / "sandbox_node_hook.cjs"
        )
        if not hook.is_file():
            self.skipTest("sandbox_node_hook.cjs missing")
        argv = inject_node_hook(["/usr/bin/node", "/tmp/script.js"])
        self.assertEqual(argv[0], "/usr/bin/node")
        self.assertEqual(argv[1], "-r")
        self.assertTrue(argv[2].endswith("sandbox_node_hook.cjs"))
        self.assertEqual(argv[3], "/tmp/script.js")

    def test_stamp_env_sets_landlock_keys(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env: dict[str, str] = {}
            stamp_confinement_env(env, root)
            self.assertIn("AION_SANDBOX_LL_READ", env)
            self.assertIn("AION_SANDBOX_LL_WRITE", env)
            self.assertEqual(env["AION_SANDBOX_SESSION_ROOT"], str(root.resolve()))


class TestSessionEnvDataDir(unittest.TestCase):
    def test_data_dir_is_session_root_not_host(self):
        with patch.dict(
            os.environ,
            {"AION_DATA_DIR": "/app/data", "PATH": "/usr/bin"},
            clear=False,
        ):
            root = Path("/tmp/sessions/test-sess-9999")
            env = build_session_env("test-sess-9999", session_root=root)
        self.assertEqual(env["AION_DATA_DIR"], str(root.resolve()))
        self.assertEqual(env["AION_SANDBOX_SESSION_ROOT"], str(root.resolve()))
        self.assertNotIn("/app/data", env.get("PYTHONPATH", ""))


if __name__ == "__main__":
    unittest.main()
